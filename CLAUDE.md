# forwarder — Claude Code Guide

TradingView → Hermes trading-signal pipeline. Two services deploy to **Railway**
from this repo, plus the Pine Script that generates the alerts.

## Layout

| Dir | Railway service | What it is |
|---|---|---|
| [`files/`](files/) | **forwarder** (webhook server) | Python FastAPI app that ingests TradingView webhooks, stores them in Postgres, and forwards them to the Hermes agent for analysis. Also runs a Telegram bot. |
| [`hermes-config/`](hermes-config/) | **hermes** (agent) | Thin Docker image over `nousresearch/hermes-agent:latest` that bakes git-managed skills into `/opt/skills-repo`. |
| `pine_script/` | — | TradingView Pine Script source that emits the schema-2.1 webhook payloads (MTF + enriched indicator blocks for the Hermes skills). Not deployed. |

The two services talk over Railway **private networking**: the forwarder calls
Hermes at `http://hermes.railway.internal:8642/v1/chat/completions` (an
OpenAI-compatible endpoint).

---

## `files/` — forwarder webhook server

- **Stack:** FastAPI + uvicorn, `psycopg` 3 (connection pool), APScheduler. Single file: `main.py`.
- **Build:** no Dockerfile — Railway auto-detects Python via Nixpacks and installs `requirements.txt`.
- **Start:** `railway.json` → `uvicorn main:app --host 0.0.0.0 --port $PORT`. Healthcheck `/health`.
- **DB:** Postgres via `DATABASE_URL`. Schema in `schema.sql` is applied automatically on startup (`migrate()` in the `lifespan` hook). Tables: `alerts` (raw payloads, deduped by `symbol+timeframe+bar_time`) and `analyses` (Hermes responses).
- **Volume:** `LOG_DIR` (default `/data/webhooks`) holds JSONL audit logs (`raw-`, `hermes-`, `errors-`, `rejected-`). Mount a Railway volume at `/data`.
- **Scheduled job:** daily cleanup of `alerts` older than 7 days (02:00 UTC / 09:00 WIB).

### Endpoints
- `POST /webhook/{token}` — TradingView ingress. Secret is in the URL path (`WEBHOOK_SECRET`) because TradingView can't set custom headers. Validates against the Pydantic `Signal` model (schema 2.0 or 2.1), dedupes by `event_id`, saves to DB. Optional source-IP allowlist via `ENFORCE_TV_IPS`.
- `POST /analyze/{token}` — manual trigger (`ANALYZE_SECRET`); analyzes the latest stored alert.
- `POST /telegram/webhook` — Telegram bot (`/analyze`, `/status`, `/start` + inline button). Verifies `x-telegram-bot-api-secret-token`; only chat IDs in `TELEGRAM_ALLOWED_CHAT_IDS` are allowed.

### Env vars (Railway)
Required: `ANALYZE_SECRET`, `WEBHOOK_SECRET`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated).
Optional (have defaults): `HERMES_URL`, `HERMES_API_KEY`, `HERMES_MODEL`, `HERMES_TIMEOUT_S`, `HERMES_SYSTEM` (system prompt routing Hermes to the `trading-confluence-orchestrator` skill), `LOG_DIR`, `DEDUPE_SIZE`, `DEFAULT_SYMBOL`, `DEFAULT_TF`, `MAX_ALERT_AGE_MIN`, `ENFORCE_TV_IPS`.

### Conventions
- Keep everything in `main.py`; comments are in Indonesian — match that style.
- Sync DB calls are wrapped in `asyncio.to_thread` so the event loop isn't blocked — keep new DB work off the loop the same way.
- Never forward the `secret` field to Hermes (stripped before the LLM call).

---

## `pine_script/` — alert payload (schema 2.1)

`xauusd_pine` builds one compact JSON per confirmed bar and sends it via `alert()`.
Blocks: `candle`, `bbma`, `ichimoku`, `liquidity_pools`, `vw_trend`, `smc`, `adx_di`,
`stoch_rsi`, `momentum_filter`, `macd`, plus top-level `mtf` (M1/M5/M15 bias snapshots),
`session`, and `bar_confirmed`.

- **Hard limit: TradingView truncates the alert message at 4096 characters.** The JSON
  currently runs ~3.7 KB — keep new fields under that ceiling or the tail is silently cut,
  producing invalid JSON that the forwarder rejects (422). `mtf` is placed early (right
  after `session`) so context survives if anything ever overflows.
- To stay small: no duplicate-alias fields (use `bb_top`/`bb_low`, `price_vs_kumo`,
  `kumo_direction`, `adx_state`, `di_bias`, `di_cross_state` — not the legacy twins), and
  `momentum_filter` carries only `analysis_timeframe` + `bar_confirmed`; its `adx_di` and
  `stoch_rsi` data live in the top-level blocks, not nested.
- If the payload must grow past the ceiling, split into two alerts (context + signal)
  rather than dropping MTF/structure fields.
- **Editing the script means re-pasting it into TradingView and recreating the alert** —
  TV runs the copy in its editor, not this repo file.

---

## `hermes-config/` — Hermes agent image

- **Build:** `railway.json` uses the `DOCKERFILE` builder. `Dockerfile` is `FROM nousresearch/hermes-agent:latest` + `COPY skills/ /opt/skills-repo/`.
- **Start:** `gateway run` (set in `railway.json`, overrides the image default).
- **Skills live in git:** `skills/<category>/<skill>/SKILL.md`. Edit → push → Railway rebuilds → agent picks them up on next deploy. They land at `/opt/skills-repo`, *outside* the `/opt/data` volume so the mount can't shadow them.
- **Volume `/opt/data`** holds runtime state (`.env`, `config.yaml`, `sessions/`, `memories/`, `skills/`, `logs/`) and is **not** in git. Secrets, port `8642`, `API_SERVER_ENABLED=true`, and private networking are configured in Railway, not here.
- **One-time setup:** merge `config.snippet.yaml` (`skills.external_dirs: [/opt/skills-repo]`) into `/opt/data/config.yaml` on the volume, then restart. See `README.md`.

### Skills
`skills/trading/`: `bbma`, `supply-demand-price-action-playbook`, `ict-smc-playbook`,
`ichimoku-filter-playbook`, `momentum-filter-stochrsi-adx-di`, `trading-confluence-orchestrator`.
Keep folder name and the frontmatter `name:` identical when adding/renaming skills.

---

## Working with Railway here
Each service's config is its own `railway.json`; set the service **root directory**
to `files/` or `hermes-config/` in Railway so the right config/build is used. Use
the `use-railway` skill for deploys, variables, volumes, and troubleshooting.

---

## Autonomous agents (multi-agent setup)

This repo is wired for autonomous improvement cycles. The `orchestrator` agent
(`.claude/agents/`) picks one task, delegates to `planner` → `implementer` / `tester`
→ `reviewer`, and opens a PR on an `agent/*` branch. This section is the source of
truth the agents read; the rules here override an agent's own defaults.

### Commands
All commands run from `files/` (the deployed app lives there).

- Install: `pip install -r files/requirements.txt -r files/requirements-dev.txt`
- Test: `cd files && pytest -q`  *(the gate — 83+ tests, DB/network-free)*
- Syntax/lint gate: `cd files && python -m compileall -q main.py backtest.py resolver.py conftest.py tests`
- Run locally (optional): `cd files && uvicorn main:app --reload` (needs the env vars in `files/CLAUDE.md`)

A change is only **done** when `pytest` passes and the `compileall` gate is clean.
There is no separate linter/formatter configured yet — do not introduce one as a
drive-by; if a backlog item asks for it, that's its own PR.

### What "improvement" means here (priority order)
1. Fix failing or flaky tests
2. Fix bugs and unhandled edge cases (payload validation, dedupe, DB/async handling)
3. Add tests for untested important code in `files/` (`main.py`, `resolver.py`, `backtest.py`)
4. Remove dead code and obvious readability problems
5. Project goal: keep the TradingView → Hermes pipeline correct and robust —
   schema 2.0/2.1 validation, dedupe integrity, and never forwarding the `secret`
   field to Hermes

### Conventions for agents
- Single-file app: keep forwarder logic in `files/main.py`. Comments are in
  **Indonesian** — match that style (see `files/CLAUDE.md`).
- Sync DB calls go through `asyncio.to_thread`; keep new DB work off the event loop.
- Tests must stay deterministic: no real network, no real DB, no `sleep`, no
  wall-clock dependence (`files/conftest.py` sets the required env + dummy DATABASE_URL).
- Commit messages: conventional commits (`feat:`, `fix:`, `test:`, `refactor:`,
  `perf:`, `docs:`, `chore:`). Branch names: `agent/<cycle-id>-<slug>`.
- No new entries in `files/requirements.txt` without justification in the PR
  (Railway installs it for production).

### Off-limits (agents must never edit)
- `.github/workflows/`, `.claude/`, this `CLAUDE.md`, `files/CLAUDE.md`, `.env*`
- `files/schema.sql` structure, and the `pine_script/` source (TV-managed; see its notes)
- Deploy config: `railway.json`, Railway variables/volumes
- Never push to `main`, never force-push, never merge PRs.
