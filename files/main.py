import hmac
import json
import logging
import os
import time
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
            """SELECT payload, bar_time FROM alerts
               WHERE symbol = %s AND timeframe = %s
               ORDER BY bar_time DESC LIMIT 1""",
            (symbol, timeframe),
        ).fetchone()
    if not row:
        return None
    return {"payload": row[0], "bar_time": row[1]}

def cleanup_old_data():
    with POOL.connection() as conn:
        r1 = conn.execute(
            "DELETE FROM alerts WHERE received_at < now() - INTERVAL '7 days'"
        )
        log.info("cleanup: %d alerts dihapus", r1.rowcount)


async def forward_to_hermes(payload: dict, received_at: str) -> None:
    headers = {"Content-Type": "application/json"}
    if HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_API_KEY}"
    body = {
        "model": HERMES_MODEL,
        "messages": [
            {
                "role": "user",
                "content": "TradingView signal payload:\n" + json.dumps(payload, ensure_ascii=False),
            }
        ],
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(HERMES_TIMEOUT_S, connect=10)) as client:
            r = await client.post(HERMES_URL, json=body, headers=headers)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        latency = round(time.monotonic() - started, 2)
        append_jsonl("hermes", {
            "received_at": received_at,
            "event_id": payload.get("event_id"),
            "latency_s": latency,
            "payload": payload,
            "response": content,
        })
        log.info("hermes ok event=%s latency=%ss", payload.get("event_id"), latency)
        # TODO: risk layer deterministik (min R:R, daily loss cap, position size) di sini,
        # SEBELUM hasil dipakai/diteruskan ke mana pun.
    except Exception as e:  # noqa: BLE001
        log.exception("hermes call failed")
        append_jsonl("errors", {"received_at": received_at, "payload": payload, "error": repr(e)})


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
async def analyze(token: str, bg: BackgroundTasks, symbol: str = "XAUUSD", timeframe: str = "15"):
    if not hmac.compare_digest(token.encode(), ANALYZE_SECRET.encode()):
        raise HTTPException(status_code=404)

    alert = fetch_latest_alert(symbol, timeframe)
    if not alert:
        raise HTTPException(status_code=404, detail=f"Belum ada alert untuk {symbol}/{timeframe}")

    age_minutes = (datetime.now(timezone.utc) - alert["bar_time"]).seconds / 60
    if age_minutes > 30:
        raise HTTPException(status_code=409, detail=f"Alert terakhir sudah {age_minutes:.0f} menit lalu, mungkin basi")

    received_at = datetime.now(timezone.utc).isoformat()
    bg.add_task(forward_to_hermes, alert["payload"], received_at)
    return {"status": "analyzing", "bar_time": alert["bar_time"].isoformat(), "age_minutes": round(age_minutes, 1)}
