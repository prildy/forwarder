import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

# --- Config (semua dari Railway env vars) ---
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
HERMES_URL = os.getenv("HERMES_URL", "http://hermes.railway.internal:8642/v1/chat/completions")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes-agent")
HERMES_TIMEOUT_S = float(os.getenv("HERMES_TIMEOUT_S", "180"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/data/webhooks"))
REQUIRED_FIELDS = [f.strip() for f in os.getenv("REQUIRED_FIELDS", "symbol,timeframe,close").split(",") if f.strip()]

# IP resmi pengirim webhook TradingView
TV_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}
ENFORCE_TV_IPS = os.getenv("ENFORCE_TV_IPS", "false").lower() == "true"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("forwarder")
app = FastAPI()


def append_jsonl(name: str, record: dict) -> None:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(LOG_DIR / f"{name}-{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


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
            "latency_s": latency,
            "payload": payload,
            "response": content,
        })
        log.info("hermes ok symbol=%s latency=%ss", payload.get("symbol"), latency)
        # TODO: risk layer deterministik (min R:R, daily loss cap, position size) di sini,
        # SEBELUM hasil dipakai/diteruskan ke mana pun.
    except Exception as e:  # noqa: BLE001
        log.exception("hermes call failed")
        append_jsonl("errors", {"received_at": received_at, "payload": payload, "error": repr(e)})


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
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing fields: {missing}")

    # Balas cepat (TradingView timeout ~3 detik); panggilan LLM jalan di background
    bg.add_task(forward_to_hermes, payload, received_at)
    return {"status": "accepted"}
