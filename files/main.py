import hmac
import json
import logging
import os
import time
import asyncio
import html
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# --- Config (semua dari Railway env vars) ---
ANALYZE_SECRET = os.environ["ANALYZE_SECRET"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
HERMES_URL = os.getenv("HERMES_URL", "http://hermes.railway.internal:8642/v1/chat/completions")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes-agent")
HERMES_TIMEOUT_S = float(os.getenv("HERMES_TIMEOUT_S", "180"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/webhooks"))
DEDUPE_SIZE = int(os.getenv("DEDUPE_SIZE", "5000"))
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "FX:XAUUSD")   # samakan dengan isi kolom symbol di DB
DEFAULT_TF = os.getenv("DEFAULT_TF", "30S")
MAX_ALERT_AGE_MIN = float(os.getenv("MAX_ALERT_AGE_MIN", "30"))
POOL = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=False)
SCHEDULER = AsyncIOScheduler(timezone="UTC")

# IP resmi pengirim webhook TradingView
TV_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}
ENFORCE_TV_IPS = os.getenv("ENFORCE_TV_IPS", "false").lower() == "true"

# --- Schema payload Pine Script (schema 2.0) ---
class _Base(BaseModel):
    # extra="allow": field baru dari Pine tidak bikin reject, tapi field wajib tetap dicek
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Candle(_Base):
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    atr: float = Field(gt=0)
    atr_len: int = Field(gt=0)

    @model_validator(mode="after")
    def ohlc_consistent(self):
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC tidak konsisten (high/low di luar open/close)")
        return self


class LiquidityPools(_Base):
    bsl_nearest: Optional[float] = None
    ssl_nearest: Optional[float] = None
    bsl_dist_atr: Optional[float] = None
    ssl_dist_atr: Optional[float] = None


class Smc(_Base):
    structure_trend: str
    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    pd_zone: Optional[str] = None


class Signal(_Base):
    schema_version: Literal["2.0"] = Field(alias="schema")
    event_id: str = Field(min_length=1)
    source: Literal["tradingview"]
    symbol: str
    ticker: str
    timeframe: str
    bar_time: datetime
    bar_time_ms: int
    triggers: list[str] = Field(min_length=1)
    candle: Candle
    liquidity_pools: LiquidityPools
    smc: Smc
    # blok indikator lain wajib ada, isinya diteruskan apa adanya ke Hermes
    bbma: dict[str, Any]
    ichimoku: dict[str, Any]
    vw_trend: dict[str, Any]
    adx_di: dict[str, Any]
    stoch_rsi: dict[str, Any]
    macd: dict[str, Any]

class StaleAlert(Exception):
    pass

# --- Dedupe berdasarkan event_id (in-memory, cukup untuk 1 instance) ---
_seen: "OrderedDict[str, None]" = OrderedDict()

def migrate():
    with POOL.connection() as conn, open("schema.sql") as f:
        conn.execute(f.read())

def save_alert(p: dict, bar_time: datetime):
    with POOL.connection() as conn:
        conn.execute(
            """INSERT INTO alerts (symbol, timeframe, bar_time, payload)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (symbol, timeframe, bar_time) DO NOTHING""",
            (p["symbol"], p["timeframe"], bar_time, Jsonb(p)),
        )

def save_analysis(alert: dict, symbol: str, timeframe: str, content: str,
                  latency_s: float, trigger_src: str) -> None:
    parsed = parse_json_loose(content)
    with POOL.connection() as conn:
        conn.execute(
            """INSERT INTO analyses
               (alert_id, symbol, timeframe, bar_time, trigger_src, latency_s, response_raw, response)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (alert["id"], symbol, timeframe, alert["bar_time"], trigger_src,
             latency_s, content, Jsonb(parsed) if parsed is not None else None),
        )


def parse_json_loose(text: str) -> dict | None:
    """LLM kadang membungkus JSON dengan ```json ... ``` — bersihkan dulu."""
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None

def already_seen(event_id: str) -> bool:
    if event_id in _seen:
        return True
    _seen[event_id] = None
    if len(_seen) > DEDUPE_SIZE:
        _seen.popitem(last=False)
    return False


def append_jsonl(name: str, record: dict) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(LOG_DIR / f"{name}-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def fetch_latest_alert(symbol: str, timeframe: str) -> dict | None:
    with POOL.connection() as conn:
        row = conn.execute(
            """SELECT id, payload, bar_time FROM alerts
               WHERE symbol = %s AND timeframe = %s
               ORDER BY bar_time DESC LIMIT 1""",
            (symbol, timeframe),
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "payload": row[1], "bar_time": row[2]}

async def run_hermes_analysis(symbol: str = DEFAULT_SYMBOL, timeframe: str = DEFAULT_TF,
                              trigger_src: str = "api") -> dict:
    # fungsi DB sync → jalankan di thread supaya event loop tidak ke-block
    alert = await asyncio.to_thread(fetch_latest_alert, symbol, timeframe)
    if not alert:
        raise LookupError(f"Belum ada alert untuk {symbol}/{timeframe}")

    age_min = (datetime.now(timezone.utc) - alert["bar_time"]).total_seconds() / 60
    if age_min > MAX_ALERT_AGE_MIN:
        raise StaleAlert(f"Alert terakhir sudah {age_min:.0f} menit lalu, mungkin basi")

    received_at = datetime.now(timezone.utc).isoformat()
    content, latency = await forward_to_hermes(alert["payload"], received_at)
    await asyncio.to_thread(save_analysis, alert, symbol, timeframe, content, latency, trigger_src)

    return {
        "symbol": symbol, "timeframe": timeframe,
        "bar_time": alert["bar_time"].isoformat(), "age_minutes": round(age_min, 1),
        "latency_s": latency, "raw": content, "plan": parse_json_loose(content),
    }

def cleanup_old_data():
    with POOL.connection() as conn:
        r1 = conn.execute(
            "DELETE FROM alerts WHERE received_at < now() - INTERVAL '7 days'"
        )
        log.info("cleanup: %d alerts dihapus", r1.rowcount)


async def forward_to_hermes(payload: dict, received_at: str) -> tuple[str, float]:
    headers = {"Content-Type": "application/json"}
    if HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_API_KEY}"
    body = {
        "model": HERMES_MODEL,
        "messages": [{"role": "user",
                      "content": "TradingView signal payload:\n" + json.dumps(payload, ensure_ascii=False)}],
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(HERMES_TIMEOUT_S, connect=10)) as client:
            r = await client.post(HERMES_URL, json=body, headers=headers)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.exception("hermes call failed")
        append_jsonl("errors", {"received_at": received_at, "payload": payload, "error": repr(e)})
        raise                       # ← penting: biar caller (API/Telegram) tahu gagal

    latency = round(time.monotonic() - started, 2)
    append_jsonl("hermes", {"received_at": received_at, "event_id": payload.get("event_id"),
                            "latency_s": latency, "payload": payload, "response": content})
    log.info("hermes ok event=%s latency=%ss", payload.get("event_id"), latency)
    return content, latency


@asynccontextmanager
async def lifespan(app: FastAPI):
    POOL.open()
    migrate()     
    
    SCHEDULER.add_job(cleanup_old_data, "cron", hour=2, minute=0)  # 09:00 WIB
    SCHEDULER.start()

    yield

    SCHEDULER.shutdown()
    POOL.close()       # jalan saat shutdown (opsional tapi bersih)


LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("forwarder")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook/{token}")
async def webhook(token: str, request: Request, bg: BackgroundTasks):
    # TradingView tidak bisa set custom header, jadi secret ditaruh di path URL
    if not hmac.compare_digest(token.encode(), WEBHOOK_SECRET.encode()):
        raise HTTPException(status_code=404)

    ip = client_ip(request)
    if ENFORCE_TV_IPS and ip not in TV_IPS:
        raise HTTPException(status_code=403)

    raw = (await request.body()).decode("utf-8", errors="replace")
    received_at = datetime.now(timezone.utc).isoformat()
    append_jsonl("raw", {"received_at": received_at, "ip": ip, "body": raw})

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("400 invalid JSON")
        raise HTTPException(status_code=400, detail="invalid JSON")

    try:
        signal = Signal.model_validate(payload)
    except ValidationError as e:
        errors = [
            {"loc": ".".join(str(p) for p in err["loc"]), "msg": err["msg"]}
            for err in e.errors()
        ]
        log.warning("422 invalid payload: %s", errors)
        append_jsonl("rejected", {"received_at": received_at, "errors": errors, "body": raw})
        raise HTTPException(status_code=422, detail=errors)

    if already_seen(signal.event_id):
        log.info("duplicate event=%s skipped", signal.event_id)
        return {"status": "duplicate"}

    # Jangan kirim field secret ke LLM
    payload.pop("secret", None)

    # Balas cepat (TradingView timeout ~3 detik);
    bg.add_task(save_alert, payload, signal.bar_time)  # ← simpan ke DB
    return {"status": "accepted", "event_id": signal.event_id}


@app.post("/analyze/{token}")
async def analyze(token: str, bg: BackgroundTasks,
                  symbol: str = DEFAULT_SYMBOL, timeframe: str = DEFAULT_TF):
    if not hmac.compare_digest(token.encode(), ANALYZE_SECRET.encode()):
        raise HTTPException(status_code=404)

    alert = await asyncio.to_thread(fetch_latest_alert, symbol, timeframe)
    if not alert:
        raise HTTPException(404, f"Belum ada alert untuk {symbol}/{timeframe}")
    age_min = (datetime.now(timezone.utc) - alert["bar_time"]).total_seconds() / 60
    if age_min > MAX_ALERT_AGE_MIN:
        raise HTTPException(409, f"Alert terakhir sudah {age_min:.0f} menit lalu, mungkin basi")

    async def _job():
        try:
            await run_hermes_analysis(symbol, timeframe, trigger_src="api")
        except Exception:  # noqa: BLE001
            log.exception("analyze job failed")

    bg.add_task(_job)
    return {"status": "analyzing", "bar_time": alert["bar_time"].isoformat(),
            "age_minutes": round(age_min, 1)}

# ===================== Telegram bot =====================
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TG_ALLOWED = {int(x) for x in os.environ["TELEGRAM_ALLOWED_CHAT_IDS"].split(",") if x.strip()}
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"
TG_MAX = 4000  # batas Telegram 4096, sisakan ruang

_analysis_lock = asyncio.Lock()  # cegah dua analisa jalan bersamaan (tombol dipencet 2x)


def analyze_button(symbol: str = DEFAULT_SYMBOL, tf: str = DEFAULT_TF) -> dict:
    return {"inline_keyboard": [[
        {"text": f"🔍 Analisa {symbol} {tf}", "callback_data": f"analyze|{symbol}|{tf}"}
    ]]}


async def tg(method: str, **payload) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{TG_API}/{method}", json=payload)
        data = r.json()
        if not data.get("ok"):
            log.warning("telegram %s gagal: %s", method, data)
        return data
    except Exception:  # noqa: BLE001
        log.exception("telegram %s error", method)
        return {"ok": False}


async def tg_send(chat_id: int, text: str, **kw) -> None:
    # pecah pesan panjang; tombol hanya di potongan terakhir
    chunks = [text[i:i + TG_MAX] for i in range(0, len(text), TG_MAX)] or [""]
    markup = kw.pop("reply_markup", None)
    for i, chunk in enumerate(chunks):
        extra = {"reply_markup": markup} if (markup and i == len(chunks) - 1) else {}
        await tg("sendMessage", chat_id=chat_id, text=chunk, **kw, **extra)


def format_plan(result: dict) -> str:
    e = html.escape
    head = (f"<b>{e(result['symbol'])} {e(result['timeframe'])}</b>\n"
            f"Bar: {e(result['bar_time'])} ({result['age_minutes']} mnt lalu)\n"
            f"Latency Hermes: {result['latency_s']}s\n\n")
    plan = result.get("plan")
    if plan is None:  # Hermes tidak mengembalikan JSON valid → tampilkan mentah
        return head + e(result["raw"])
    # Generik: tampilkan semua field top-level. Sesuaikan setelah struktur JSON-nya pasti.
    lines = []
    for k, v in plan.items():
        val = v if isinstance(v, (str, int, float)) else json.dumps(v, ensure_ascii=False)
        lines.append(f"<b>{e(str(k))}</b>: {e(str(val))}")
    return head + "\n".join(lines)


async def tg_do_analysis(chat_id: int, symbol: str, tf: str) -> None:
    if _analysis_lock.locked():
        await tg_send(chat_id, "⏳ Masih ada analisa yang berjalan, tunggu sebentar.")
        return
    async with _analysis_lock:
        await tg_send(chat_id, f"⏳ Menganalisa {html.escape(symbol)} {html.escape(tf)}...")
        try:
            result = await run_hermes_analysis(symbol, tf, trigger_src="telegram")
            text = format_plan(result)
        except (LookupError, StaleAlert) as ex:
            text = f"⚠️ {html.escape(str(ex))}"
        except Exception as ex:  # noqa: BLE001
            log.exception("telegram analysis failed")
            text = f"❌ Analisa gagal: {html.escape(repr(ex))[:500]}"
        await tg_send(chat_id, text, parse_mode="HTML", reply_markup=analyze_button(symbol, tf))


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, bg: BackgroundTasks):
    secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(secret.encode(), TG_SECRET.encode()):
        raise HTTPException(status_code=403)

    update = await request.json()

    # --- tombol inline ---
    if cq := update.get("callback_query"):
        await tg("answerCallbackQuery", callback_query_id=cq["id"])
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        if chat_id in TG_ALLOWED and cq.get("data", "").startswith("analyze|"):
            _, symbol, tf = cq["data"].split("|", 2)
            bg.add_task(tg_do_analysis, chat_id, symbol, tf)
        return {"ok": True}

    # --- pesan / command ---
    msg = update.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if chat_id not in TG_ALLOWED:
        log.info("telegram: chat %s tidak diizinkan, diabaikan", chat_id)
        return {"ok": True}

    cmd, *args = text.split() or [""]
    cmd = cmd.split("@")[0].lower()   # handle "/analyze@NamaBot"

    if cmd == "/start":
        await tg_send(chat_id, "Siap. Tekan tombol atau ketik /analyze [symbol] [tf].",
                      reply_markup=analyze_button())
    elif cmd == "/analyze":
        symbol = args[0].upper() if len(args) > 0 else DEFAULT_SYMBOL
        tf = args[1] if len(args) > 1 else DEFAULT_TF
        bg.add_task(tg_do_analysis, chat_id, symbol, tf)
    elif cmd == "/status":
        alert = await asyncio.to_thread(fetch_latest_alert, DEFAULT_SYMBOL, DEFAULT_TF)
        if alert:
            age = (datetime.now(timezone.utc) - alert["bar_time"]).total_seconds() / 60
            await tg_send(chat_id, f"Alert terakhir {DEFAULT_SYMBOL} {DEFAULT_TF}: "
                                   f"{alert['bar_time'].isoformat()} ({age:.0f} mnt lalu)",
                          reply_markup=analyze_button())
        else:
            await tg_send(chat_id, "Belum ada alert tersimpan.")

    return {"ok": True}