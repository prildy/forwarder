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
# System prompt: arahkan agent ke trading-confluence-orchestrator & kontrak output JSON.
# Kontrak JSON di bawah dikonsumsi dua konsumen: tampilan /analyze Telegram (format_plan)
# dan forward auto-capture (parse_hermes_decision). Jangan ubah nama field tanpa update
# kedua konsumen itu.
HERMES_SYSTEM = os.getenv(
    "HERMES_SYSTEM",
    "You are a trading decision-support analyst for XAUUSD (paper-only, no broker "
    "execution). Use the trading-confluence-orchestrator skill, which coordinates the "
    "bbma, ict-smc, supply-demand, ichimoku, and momentum-filter skills. Base every "
    "factual claim only on the payload (candle, bbma, ichimoku, liquidity_pools, "
    "vw_trend, smc, adx_di, stoch_rsi, momentum_filter, macd, and the mtf multi-"
    "timeframe block); never invent prices or states. Do not treat the 30S bar as a "
    "standalone bias source — use the mtf block for higher-timeframe context. List any "
    "absent fields under missing_data. "
    "You MUST return a single JSON object and nothing else — no prose, no Markdown "
    "fences, no code blocks. The object MUST have exactly these keys: "
    '"decision" (one of "long", "short", "no_trade"), '
    '"entry" (number or null), "stop_loss" (number or null), '
    '"take_profit" (number or null), "confidence" (number 0.0-1.0), '
    '"setup_tags" (array of strings), "rationale" (short string), '
    '"missing_data" (array of strings). '
    "When decision is \"long\" or \"short\", entry/stop_loss/take_profit MUST be numbers "
    "drawn from the payload levels, with sl and tp on the correct sides of entry "
    "(long: sl < entry < tp; short: tp < entry < sl). When decision is \"no_trade\", set "
    "entry/stop_loss/take_profit to null. confidence reflects how strong the confluence "
    "is for the stated decision.",
)
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

# --- Forward auto-capture (Hermes-driven forward test) ---
# Master switch: kalau false, webhook cuma simpan alert (persis seperti sebelumnya),
# tidak ada panggilan Hermes dan tidak ada jurnal yang dibuat.
FORWARD_AUTOCAPTURE = os.getenv("FORWARD_AUTOCAPTURE", "false").lower() == "true"
# Daftar trigger yang memenuhi syarat (comma-separated). Kosong = trigger apa pun asal
# daftar triggers di payload tidak kosong. Ini keputusan kebijakan trading user.
FORWARD_TRIGGERS = {
    t.strip() for t in os.getenv("FORWARD_TRIGGERS", "").split(",") if t.strip()
}
# Ambang confidence minimum dari Hermes; di bawah ini capture dilewati.
FORWARD_MIN_CONFIDENCE = float(os.getenv("FORWARD_MIN_CONFIDENCE", "0.6"))

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
    # terima 2.0 (lama) dan 2.1 (schema diperkaya untuk semua skill Hermes)
    schema_version: Literal["2.0", "2.1"] = Field(alias="schema")
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
    # blok baru schema 2.1 (opsional supaya payload 2.0 lama tetap lolos):
    # bar_confirmed + session dipakai orchestrator untuk data-quality gate,
    # momentum_filter = blok gabungan yang diminta momentum skill,
    # mtf = konteks multi-timeframe (semua skill melarang bias dari 30S saja).
    bar_confirmed: Optional[bool] = None
    session: Optional[str] = None
    momentum_filter: dict[str, Any] = {}
    mtf: dict[str, Any] = {}

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

def _coerce_float(value: Any) -> float | None:
    # Level harga harus angka; string "na"/null/teks → None supaya gate di hulu aman.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def parse_hermes_decision(content: str) -> dict | None:
    """Normalkan respons Hermes jadi dict keputusan trade, atau None kalau tak terpakai.

    Defensif: confidence hilang/na → 0.0; level non-numerik → None. Field decision wajib
    salah satu dari long/short/no_trade; selain itu dianggap tak terpakai (None).
    """
    parsed = parse_json_loose(content)
    if parsed is None:
        return None

    decision = parsed.get("decision")
    if not isinstance(decision, str) or decision.lower() not in ("long", "short", "no_trade"):
        return None

    confidence = _coerce_float(parsed.get("confidence"))
    if confidence is None:
        confidence = 0.0

    setup_tags = parsed.get("setup_tags")
    if not isinstance(setup_tags, list):
        setup_tags = []
    setup_tags = [str(tag) for tag in setup_tags if isinstance(tag, (str, int, float))]

    return {
        "decision": decision.lower(),
        "entry": _coerce_float(parsed.get("entry")),
        "stop_loss": _coerce_float(parsed.get("stop_loss")),
        "take_profit": _coerce_float(parsed.get("take_profit")),
        "confidence": confidence,
        "setup_tags": setup_tags,
    }


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

# ===================== Trade journal (DB helpers) =====================
# Semua fungsi di sini sinkron (pakai POOL) → dipanggil lewat asyncio.to_thread.


def classify_r(r_multiple: float) -> str:
    # Breakeven kalau R mendekati nol; kecuali itu menang/kalah dari tanda R.
    if abs(r_multiple) < 0.05:
        return "breakeven"
    return "win" if r_multiple > 0 else "loss"


def create_journal_entry(symbol: str, timeframe: str, mode: str, direction: str,
                         entry: float, stop_loss: float, take_profit: float,
                         setup_tags: list[str], alert_id: int | None,
                         analysis_id: int | None) -> int:
    with POOL.connection() as conn:
        row = conn.execute(
            """INSERT INTO journal
               (symbol, timeframe, mode, direction, entry, stop_loss, take_profit,
                setup_tags, alert_id, analysis_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (symbol, timeframe, mode, direction, entry, stop_loss, take_profit,
             setup_tags, alert_id, analysis_id),
        ).fetchone()
    return row[0]


def has_open_forward_trade(symbol: str, timeframe: str) -> bool:
    # Anti-pyramiding: cek apakah masih ada forward trade open untuk symbol+tf ini.
    with POOL.connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM journal
               WHERE mode = 'forward' AND symbol = %s AND timeframe = %s
                 AND status = 'open'
               LIMIT 1""",
            (symbol, timeframe),
        ).fetchone()
    return row is not None


def fetch_journal(journal_id: int) -> dict | None:
    with POOL.connection() as conn:
        row = conn.execute(
            """SELECT id, symbol, timeframe, direction, entry, stop_loss, take_profit, status
               FROM journal WHERE id = %s""",
            (journal_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "symbol": row[1], "timeframe": row[2], "direction": row[3],
            "entry": row[4], "stop_loss": row[5], "take_profit": row[6], "status": row[7]}


def close_journal_entry(journal_id: int, exit_price: float, r_multiple: float,
                        status: str, lesson: str | None) -> bool:
    # WHERE status='open' bikin idempoten: baris yang sudah tertutup tidak tersentuh.
    with POOL.connection() as conn:
        result = conn.execute(
            """UPDATE journal
               SET exit_price = %s, r_multiple = %s, status = %s, lesson = %s, closed_at = now()
               WHERE id = %s AND status = 'open'""",
            (exit_price, r_multiple, status, lesson, journal_id),
        )
    return result.rowcount > 0


def resolve_open_trades() -> int:
    # Auto-resolve murni dari bar alerts yang sudah tersimpan — tanpa panggilan eksternal.
    resolved = 0
    with POOL.connection() as conn:
        open_trades = conn.execute(
            """SELECT id, symbol, timeframe, direction, entry, stop_loss, take_profit, opened_at
               FROM journal WHERE status = 'open'"""
        ).fetchall()

        for trade in open_trades:
            (journal_id, symbol, timeframe, direction, entry,
             stop_loss, take_profit, opened_at) = trade

            # Risk dihitung dulu supaya bisa guard pembagian nol sebelum menelusuri bar.
            risk = (entry - stop_loss) if direction == "long" else (stop_loss - entry)
            if risk == 0:
                log.warning("journal %s: risk nol (entry == sl), lewati auto-resolve", journal_id)
                continue

            # Ambil high/low tiap bar setelah entry, urut waktu naik.
            bars = conn.execute(
                """SELECT bar_time,
                          (payload->'candle'->>'high')::numeric AS high,
                          (payload->'candle'->>'low')::numeric  AS low
                   FROM alerts
                   WHERE symbol = %s AND timeframe = %s AND bar_time > %s
                   ORDER BY bar_time ASC""",
                (symbol, timeframe, opened_at),
            ).fetchall()

            for (bar_time, bar_high, bar_low) in bars:
                if bar_high is None or bar_low is None:
                    continue

                if direction == "long":
                    hit_tp = bar_high >= take_profit
                    hit_sl = bar_low <= stop_loss
                else:  # short
                    hit_tp = bar_low <= take_profit
                    hit_sl = bar_high >= stop_loss

                if not hit_tp and not hit_sl:
                    continue

                # Worst-case intrabar: kalau satu bar menyentuh SL dan TP sekaligus,
                # anggap LOSS (asumsi jujur/konservatif, bukan optimis TP duluan).
                if hit_sl:
                    status, exit_price = "loss", stop_loss
                else:
                    status, exit_price = "win", take_profit

                reward = (exit_price - entry) if direction == "long" else (entry - exit_price)
                r_multiple = reward / risk

                conn.execute(
                    """UPDATE journal
                       SET status = %s, exit_price = %s, r_multiple = %s, closed_at = %s
                       WHERE id = %s AND status = 'open'""",
                    (status, exit_price, r_multiple, bar_time, journal_id),
                )
                resolved += 1
                break  # bar pertama yang menyentuh level menentukan hasil
    return resolved


def fetch_open_trades(limit: int = 20) -> list[dict]:
    with POOL.connection() as conn:
        rows = conn.execute(
            """SELECT id, mode, symbol, timeframe, direction, entry, stop_loss, take_profit, opened_at
               FROM journal WHERE status = 'open'
               ORDER BY opened_at DESC LIMIT %s""",
            (limit,),
        ).fetchall()
    return [
        {"id": r[0], "mode": r[1], "symbol": r[2], "timeframe": r[3], "direction": r[4],
         "entry": r[5], "stop_loss": r[6], "take_profit": r[7], "opened_at": r[8]}
        for r in rows
    ]


def journal_stats(symbol: str, mode: str) -> dict:
    # Agregat per symbol+mode: hitung menang/kalah/BE dan rata-rata R trade yang sudah selesai.
    with POOL.connection() as conn:
        row = conn.execute(
            """SELECT
                 count(*) FILTER (WHERE status = 'win')       AS wins,
                 count(*) FILTER (WHERE status = 'loss')      AS losses,
                 count(*) FILTER (WHERE status = 'breakeven') AS breakevens,
                 count(*) FILTER (WHERE status = 'open')      AS opens,
                 avg(r_multiple) FILTER (WHERE status IN ('win', 'loss', 'breakeven')) AS avg_r
               FROM journal WHERE symbol = %s AND mode = %s""",
            (symbol, mode),
        ).fetchone()
    wins, losses, breakevens, opens, avg_r = row
    closed = wins + losses + breakevens
    win_rate = (wins / closed * 100) if closed else 0.0
    return {
        "symbol": symbol, "mode": mode,
        "wins": wins, "losses": losses, "breakevens": breakevens, "opens": opens,
        "win_rate": round(win_rate, 1),
        "avg_r": round(float(avg_r), 2) if avg_r is not None else None,
    }


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

def _triggers_qualify(triggers: list[str]) -> bool:
    # Kosongnya FORWARD_TRIGGERS artinya "trigger apa pun asal daftar tidak kosong".
    if not triggers:
        return False
    if not FORWARD_TRIGGERS:
        return True
    return bool(set(triggers) & FORWARD_TRIGGERS)


def _levels_sane(direction: str, entry: float, stop_loss: float, take_profit: float) -> bool:
    # long: sl < entry < tp; short: tp < entry < sl.
    if direction == "long":
        return stop_loss < entry < take_profit
    return take_profit < entry < stop_loss


async def forward_autocapture(payload: dict, bar_time: datetime) -> None:
    """Hermes-driven forward test: dari satu signal live, minta keputusan ke Hermes,
    lalu kalau layak buat jurnal mode='forward' yang nanti ditutup resolver 1 menit.

    Seluruh badan dibungkus try/except: kegagalan apa pun (Hermes mati, parse jelek)
    dicatat lalu ditelan — tidak boleh mengganggu ingesti webhook.
    """
    if not FORWARD_AUTOCAPTURE:
        return

    try:
        symbol = payload.get("symbol")
        timeframe = payload.get("timeframe")
        # Gate instrumen utama: forward-capture hanya untuk DEFAULT_SYMBOL/DEFAULT_TF.
        if symbol != DEFAULT_SYMBOL or timeframe != DEFAULT_TF:
            log.debug("autocapture skip: symbol/tf bukan primary (%s/%s)", symbol, timeframe)
            return

        triggers = payload.get("triggers") or []
        if not _triggers_qualify(triggers):
            log.debug("autocapture skip: triggers tidak memenuhi filter (%s)", triggers)
            return

        # Anti-pyramiding: satu forward trade open per symbol+tf.
        if await asyncio.to_thread(has_open_forward_trade, symbol, timeframe):
            log.info("autocapture skip: masih ada forward trade open %s/%s", symbol, timeframe)
            return

        received_at = datetime.now(timezone.utc).isoformat()
        content, _ = await forward_to_hermes(payload, received_at)
        decision = parse_hermes_decision(content)
        if decision is None:
            log.info("autocapture skip: respons Hermes tak terparse jadi keputusan")
            return

        if decision["decision"] not in ("long", "short"):
            log.info("autocapture skip: decision=%s (no_trade)", decision["decision"])
            return

        if decision["confidence"] < FORWARD_MIN_CONFIDENCE:
            log.info("autocapture skip: confidence %.2f < %.2f",
                     decision["confidence"], FORWARD_MIN_CONFIDENCE)
            return

        entry = decision["entry"]
        stop_loss = decision["stop_loss"]
        take_profit = decision["take_profit"]
        if entry is None or stop_loss is None or take_profit is None:
            log.info("autocapture skip: level entry/sl/tp tidak lengkap")
            return

        if not _levels_sane(decision["decision"], entry, stop_loss, take_profit):
            log.info("autocapture skip: level tidak masuk akal utk %s (e=%s sl=%s tp=%s)",
                     decision["decision"], entry, stop_loss, take_profit)
            return

        # Tautkan alert terbaru (yang baru saja disimpan) sebagai konteks jurnal.
        alert = await asyncio.to_thread(fetch_latest_alert, symbol, timeframe)
        alert_id = alert["id"] if alert else None

        setup_tags = decision["setup_tags"] or list(triggers)
        journal_id = await asyncio.to_thread(
            create_journal_entry, symbol, timeframe, "forward", decision["decision"],
            entry, stop_loss, take_profit, setup_tags, alert_id, None,
        )
        log.info("autocapture: jurnal forward #%s dibuat %s e=%s sl=%s tp=%s conf=%.2f",
                 journal_id, decision["decision"], entry, stop_loss, take_profit,
                 decision["confidence"])
    except Exception:  # noqa: BLE001
        log.exception("autocapture gagal (diabaikan, webhook tetap aman)")


async def ingest_signal(payload: dict, bar_time: datetime) -> None:
    # Satu background task: simpan alert dulu (supaya id-nya ada), baru auto-capture
    # yang melihat alert tsb. Urutan ini menghindari race antara save & lookup.
    await asyncio.to_thread(save_alert, payload, bar_time)
    await forward_autocapture(payload, bar_time)


def cleanup_old_data():
    with POOL.connection() as conn:
        r1 = conn.execute(
            "DELETE FROM alerts WHERE received_at < now() - INTERVAL '7 days'"
        )
        log.info("cleanup: %d alerts dihapus", r1.rowcount)


async def _resolve_job():
    # Job scheduler: resolve trade open terhadap bar baru. DB sync → lempar ke thread.
    n = await asyncio.to_thread(resolve_open_trades)
    if n:
        log.info("resolver: %d trade ditutup otomatis", n)


async def forward_to_hermes(payload: dict, received_at: str) -> tuple[str, float]:
    headers = {"Content-Type": "application/json"}
    if HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_API_KEY}"
    messages = []
    if HERMES_SYSTEM:
        messages.append({"role": "system", "content": HERMES_SYSTEM})
    messages.append({"role": "user",
                     "content": "TradingView signal payload:\n" + json.dumps(payload, ensure_ascii=False)})
    body = {
        "model": HERMES_MODEL,
        "messages": messages,
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
    # Resolver tiap 1 menit: cocok untuk TF scalping 30S, bar baru cepat ketahuan.
    SCHEDULER.add_job(_resolve_job, "interval", minutes=1)
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

    # Balas cepat (TradingView timeout ~3 detik); satu task simpan alert lalu
    # (kalau FORWARD_AUTOCAPTURE aktif) jalankan Hermes-driven forward capture.
    bg.add_task(ingest_signal, payload, signal.bar_time)
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


async def tg_cmd_journal(chat_id: int, args: list[str]) -> None:
    # /journal [live|forward] <long|short> <entry> <sl> <tp> [tag1,tag2,...]
    usage = ("Format: /journal [live|forward] <long|short> <entry> <sl> <tp> [tag1,tag2]\n"
             "Contoh: /journal live long 2650.5 2648 2655 bbma,reentry")
    parts = list(args)

    # Mode opsional di depan; default 'live'.
    mode = "live"
    if parts and parts[0].lower() in ("live", "forward"):
        mode = parts.pop(0).lower()

    if len(parts) < 4:
        await tg_send(chat_id, usage)
        return

    direction = parts[0].lower()
    if direction not in ("long", "short"):
        await tg_send(chat_id, usage)
        return

    try:
        entry = float(parts[1])
        stop_loss = float(parts[2])
        take_profit = float(parts[3])
    except ValueError:
        await tg_send(chat_id, usage)
        return

    # Tag opsional: "tag1,tag2" → list.
    setup_tags: list[str] = []
    if len(parts) >= 5:
        setup_tags = [t.strip() for t in parts[4].split(",") if t.strip()]

    # Sanity: long harus sl<entry<tp, short harus tp<entry<sl. Warning saja, bukan blok keras.
    warn = ""
    if direction == "long" and not (stop_loss < entry < take_profit):
        warn = "\n⚠️ Catatan: untuk long normalnya sl < entry < tp."
    elif direction == "short" and not (take_profit < entry < stop_loss):
        warn = "\n⚠️ Catatan: untuk short normalnya tp < entry < sl."

    # Tautkan alert terbaru sebagai konteks; analysis_id dibiarkan NULL dulu.
    alert = await asyncio.to_thread(fetch_latest_alert, DEFAULT_SYMBOL, DEFAULT_TF)
    alert_id = alert["id"] if alert else None

    journal_id = await asyncio.to_thread(
        create_journal_entry, DEFAULT_SYMBOL, DEFAULT_TF, mode, direction,
        entry, stop_loss, take_profit, setup_tags, alert_id, None,
    )

    e = html.escape
    tags_txt = ", ".join(setup_tags) if setup_tags else "-"
    summary = (f"✅ Jurnal #<b>{journal_id}</b> dibuat\n"
               f"{e(mode)} {e(direction)} {e(DEFAULT_SYMBOL)} {e(DEFAULT_TF)}\n"
               f"entry {entry} | sl {stop_loss} | tp {take_profit}\n"
               f"tags: {e(tags_txt)}")
    await tg_send(chat_id, summary + e(warn), parse_mode="HTML")


async def tg_cmd_close(chat_id: int, args: list[str]) -> None:
    # /close <id> <exit_price> [lesson text...]
    usage = ("Format: /close <id> <exit_price> [catatan pelajaran...]\n"
             "Contoh: /close 12 2653.2 entry telat, kejar harga")
    if len(args) < 2:
        await tg_send(chat_id, usage)
        return

    try:
        journal_id = int(args[0])
        exit_price = float(args[1])
    except ValueError:
        await tg_send(chat_id, usage)
        return

    lesson = " ".join(args[2:]).strip() or None

    trade = await asyncio.to_thread(fetch_journal, journal_id)
    if trade is None:
        await tg_send(chat_id, f"❌ Jurnal #{journal_id} tidak ditemukan.")
        return
    if trade["status"] != "open":
        await tg_send(chat_id, f"❌ Jurnal #{journal_id} sudah ditutup (status: {trade['status']}).")
        return

    # Kolom NUMERIC balik sebagai Decimal; paksa float supaya aman dipadu exit_price float.
    entry = float(trade["entry"])
    stop_loss = float(trade["stop_loss"])
    direction = trade["direction"]
    if direction == "long":
        risk = entry - stop_loss
        reward = exit_price - entry
    else:
        risk = stop_loss - entry
        reward = entry - exit_price
    if risk == 0:
        await tg_send(chat_id, f"❌ Jurnal #{journal_id}: risk nol (entry == sl), R tak terhitung.")
        return

    r_multiple = reward / risk
    status = classify_r(r_multiple)

    ok = await asyncio.to_thread(
        close_journal_entry, journal_id, exit_price, r_multiple, status, lesson
    )
    if not ok:
        await tg_send(chat_id, f"❌ Jurnal #{journal_id} gagal ditutup (mungkin sudah tertutup).")
        return

    e = html.escape
    txt = (f"✅ Jurnal #<b>{journal_id}</b> ditutup: <b>{e(status)}</b>\n"
           f"exit {exit_price} | R {r_multiple:+.2f}")
    if lesson:
        txt += f"\nPelajaran: {e(lesson)}"
    await tg_send(chat_id, txt, parse_mode="HTML")


async def tg_cmd_trades(chat_id: int) -> None:
    # Daftar trade open + satu baris stats ringkas untuk DEFAULT_SYMBOL.
    trades = await asyncio.to_thread(fetch_open_trades, 20)
    stats = await asyncio.to_thread(journal_stats, DEFAULT_SYMBOL, "live")

    e = html.escape
    now = datetime.now(timezone.utc)
    if not trades:
        lines = ["Tidak ada trade open."]
    else:
        lines = [f"<b>Trade open ({len(trades)})</b>"]
        for t in trades:
            age_min = (now - t["opened_at"]).total_seconds() / 60
            lines.append(
                f"#<b>{t['id']}</b> {e(t['mode'])} {e(t['direction'])} "
                f"entry {t['entry']} sl {t['stop_loss']} tp {t['take_profit']} "
                f"({age_min:.0f} mnt)"
            )

    avg_r = stats["avg_r"]
    avg_r_txt = f"{avg_r:+.2f}" if avg_r is not None else "-"
    stat_line = (f"\n<b>Stats {e(DEFAULT_SYMBOL)} (live)</b>: "
                 f"W {stats['wins']} / L {stats['losses']} / BE {stats['breakevens']} "
                 f"· winrate {stats['win_rate']}% · avgR {avg_r_txt}")
    await tg_send(chat_id, "\n".join(lines) + "\n" + stat_line, parse_mode="HTML")


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
    elif cmd == "/journal":
        await tg_cmd_journal(chat_id, args)
    elif cmd == "/close":
        await tg_cmd_close(chat_id, args)
    elif cmd == "/trades":
        await tg_cmd_trades(chat_id)

    return {"ok": True}