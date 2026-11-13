# Backlog

The orchestrator agent picks the top unchecked item each cycle and ticks it (`- [x]`)
in its PR. Edit this file to steer the agent — keep items **small** (under ~300 changed
lines), specific, and verifiable by `pytest`.

Paths are relative to the repo root; the forwarder app lives in `files/`.

- [x] Add unit tests for `resolver.py` edge cases that aren't yet covered in `files/tests/test_resolver.py` (document which paths are untested before adding).
- [x] Add tests for the `Signal` Pydantic model in `files/main.py` — reject malformed schema-2.0 / 2.1 payloads (missing blocks, out-of-range values) and assert the 422 path.
- [x] Harden `files/main.py` webhook dedupe (`event_id` / `symbol+timeframe+bar_time`) against duplicate alerts arriving out of order; add a regression test.
- [x] Audit `files/main.py` for any DB call not wrapped in `asyncio.to_thread` and move it off the event loop (per the `files/` conventions in `CLAUDE.md`); add a test if feasible.

---

# Action plan: make the XAUUSD bot measurable, then improvable (added 2026-11-13)

**Why this plan exists.** A review found that the pipeline cannot yet tell whether the bot
has an edge: the stored price history has holes, fills are assumed, there are no trading
costs, rejected decisions are not recorded, the backtest tests a different rule than the
live LLM, and the forwarder and the Hermes skill disagree on the output format. The items
below fix that in order: **M** = measurement, **D** = decision layer, **R** = risk
controls, **P** = reporting and polish.

**Decisions already made by the owner — do not revisit:**
- The 7-day `alerts` cleanup (`cleanup_old_data` in `files/main.py`) **stays as is**. Do not
  change, disable or extend it. It keeps the database from bloating.
- The bot stays **paper / suggestion only**. No broker execution code in any item.

## Rules for whoever implements an item (read first)

1. Read `CLAUDE.md`. Its rules win over anything here. Do exactly **one** item per PR, in
   the order listed. Each item is one checkbox; the indented bullets under it are its spec.
2. Never edit: `files/schema.sql`, `pine_script/`, any `railway.json`, `.github/workflows/`,
   `.claude/`, `CLAUDE.md`, `pytest.ini`. If an item says **"Requires H<n>"**, first check
   that the human step is done (the check is written in the item). If it is not done,
   **stop and report blocked** — do not work around it.
3. Every new behaviour is controlled by an env var read at module import in `files/main.py`
   (same style as `FORWARD_MIN_CONFIDENCE`). Use the exact names and defaults given. Tests
   override them with `monkeypatch.setattr(main, "NAME", value)`.
4. New parameters on existing functions must have defaults that keep today's behaviour, so
   existing tests pass unchanged — unless the item explicitly says a test must be updated.
   Never delete or weaken a test; updating an expected value because the item changes that
   behaviour on purpose is allowed and must be listed in the PR.
5. Style: comments in Indonesian. `main.py` uses 4-space indentation; `resolver.py`,
   `backtest.py` and all tests use 2-space. Money/price maths in `resolver.py` and
   `backtest.py` is `Decimal` only (convert floats with `Decimal(str(x))`).
6. Tests: no network, no DB, no `sleep`, no wall-clock. Async code is run with
   `asyncio.run(...)` (no pytest-asyncio). DB code is tested with the `_FakePool` /
   `_FakeConn` / `_FakeCursor` helpers already in `files/tests/test_main.py`. When new code
   needs "now", call a module-level `def _utcnow() -> datetime` in `main.py` (create it in
   the first item that needs it: `return datetime.now(timezone.utc)`) so tests can
   monkeypatch it.
7. No new entries in `files/requirements.txt`.
8. Done = `pytest -q` green and the `compileall` gate from `CLAUDE.md` clean.

## Human-only steps (NOT for agents — no checkboxes on purpose)

These touch off-limits files or things outside the repo. The owner does them (or gives a
one-off explicit instruction to an implementer).

- **H1 — additive schema columns.** Append to the end of `files/schema.sql` (idempotent,
  applied by `migrate()` on next deploy). Needed by M5, M6, M7.
  ```sql
  ALTER TABLE analyses ADD COLUMN IF NOT EXISTS capture_outcome TEXT;
  ALTER TABLE journal  ADD COLUMN IF NOT EXISTS gross_r   NUMERIC;
  ALTER TABLE journal  ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ;
  ```
- **H2 — send every bar from TradingView.** After M1 is deployed: in the indicator
  settings set "Kirim alert saat" = `Every bar close` (the option already exists in
  `pine_script/xauusd_pine`, no script edit) and recreate the alert. Confirm in the
  `alerts` table that consecutive 30S bars arrive and that TradingView does not auto-stop
  the alert for firing too often. Needed before M5's defaults are meaningful.
- **H3 — Railway variables.** (a) Check whether `HERMES_SYSTEM` is set on the forwarder
  service; if it is, delete it after D1 ships so the new default in code is used. (b) Set
  the new variables as items ship (each item lists its names and defaults).
- **H4 — confirm trading-policy numbers.** The defaults below are placeholders chosen by
  the reviewer, not measured: `COST_SPREAD=0.30` (ask the friend's broker for the real
  XAUUSD spread), `COST_SLIPPAGE=0.05`, sessions `london,overlap,newyork`, min R:R 1.5,
  daily stop −3R, max 10 trades/day, and the default strategy record in D2.
- **H5 — price feed.** The chart symbol is `FX:XAUUSD`; the friend's broker quotes
  different prices. If TradingView offers that broker's feed, switch the chart and set
  `DEFAULT_SYMBOL` to match.
- **H6 — gates for the new module.** After D3, add `files/strategy.py` to the
  `compileall` command in `CLAUDE.md` and `.github/workflows/ci.yml`.
- **H7 — repo hygiene.** `git worktree prune`, then `git gc --prune=now` (`.git` is 13 GB
  from 178 orphaned `tmp_obj_*` files in `.git/objects/3c`). Pin
  `hermes-config/Dockerfile` to a version tag or digest instead of `:latest`. The local
  `.claude/settings.json` is modified and much smaller than the one on `main` — restore it
  if that was not intended. Consider moving `.devx/` and `.mcp.json` (employer tooling)
  out of this folder.

---

## Phase M — make the scorekeeping honest

- [x] **M1 — Accept bars with no triggers, so every closed bar can be stored.**
  - Problem: `Signal.triggers` in `files/main.py` is `Field(min_length=1)`, so
    "Every bar close" payloads with `"triggers": []` get a 422 and are never stored. The
    resolver and backtest then only see trigger bars and miss SL/TP touches in between.
  - Change: in class `Signal`, make it `triggers: list[str]` (key still required, list may
    be empty). Change nothing else in the model.
  - Must stay true (verify, do not change): `_triggers_qualify([])` returns `False`, so a
    no-trigger bar never reaches Hermes; `backtest.generate_trades` counts it under
    `no_trigger`.
  - Tests (`files/tests/test_signal.py`): remove the `("triggers", [])` case from the
    parametrized bad-values list (intended behaviour change — say so in the PR); add
    `test_signal_empty_triggers_accepted`, `test_signal_missing_triggers_key_still_rejected`,
    and `test_webhook_empty_triggers_accepted_and_ingested` (copy the structure of
    `test_webhook_happy_path_strips_secret`). In `files/tests/test_main.py` add
    `test_forward_autocapture_empty_triggers_never_calls_hermes`.

- [x] **M2 — `resolver.py`: trading costs and richer result fields.**
  - Only `files/resolver.py` and `files/tests/test_resolver.py`.
  - `PriceBar`: add `close: Optional[Decimal] = None` as the last field. Add `close` to the
    `PriceBarLike` protocol docstring, but read it everywhere with
    `getattr(bar, "close", None)` because duck-typed bars in tests may not have it.
  - `Resolution`: add at the end, all defaulting to `None`: `gross_r: Optional[Decimal]`,
    `filled_at: Optional[datetime]`, `exit_reason: Optional[str]` (values used by this and
    later items: `"tp"`, `"sl"`, `"no_fill"`, `"timeout"`). `OPEN` sentinel unchanged.
  - `resolve(...)`: add keyword-only `cost: Decimal = Decimal(0)` = round-trip cost in
    price units (spread + slippage both sides). Raise `ValueError` if `cost < 0`.
    On a touch: `gross_r = reward / risk`; `r_multiple = gross_r - (cost / risk)`;
    set `exit_reason` to `"sl"` or `"tp"`. `status` is still decided by which level was
    touched (a TP touch stays `"win"` even if costs make `r_multiple` negative).
  - Add `def classify_r(r: Decimal) -> str` with the same thresholds as `main.classify_r`
    (`abs(r) < Decimal("0.05")` → `"breakeven"`, else sign). Used by M4.
  - Tests: cost 0 gives `r_multiple == gross_r`; long TP at 2R with risk 2.0 and cost 0.4
    gives `gross_r == 2` and `r_multiple == Decimal("1.8")`; SL gives `gross_r == -1`,
    `r_multiple == Decimal("-1.2")`; short mirror; negative cost raises; `exit_reason`
    values; `classify_r` boundaries. All existing resolver tests must pass untouched.

- [x] **M3 — `resolver.py`: entry-fill model (stop assuming every trade is filled).**
  - Only `files/resolver.py` and `files/tests/test_resolver.py`.
  - `resolve(...)`: add keyword-only `require_fill: bool = False` and
    `max_fill_bars: Optional[int] = None`. With `require_fill=False` nothing changes.
  - With `require_fill=True`, walk the bars in order. Bars whose `high` or `low` is `None`
    are skipped and **not counted**. For each counted bar, until filled:
    - Filled if `bar.low <= entry <= bar.high`, **or** price jumped across the entry
      between the previous counted bar and this one (`prev.high < entry and bar.low > entry`,
      or `prev.low > entry and bar.high < entry`). Fill price is always `entry`.
    - If not filled and `max_fill_bars` is set and this is counted bar number
      `max_fill_bars`: return `Resolution(status="skipped", exit_price=None,
      r_multiple=None, closed_at=bar.bar_time, exit_reason="no_fill")`.
  - On the fill bar: set `filled_at = bar.bar_time`. Check **only the stop** on that bar
    (worst case): if the stop is touched → loss as in M2. Never credit a take-profit on
    the fill bar. From the next bar on, normal SL/TP logic (tie → loss).
  - Bars run out before a fill → return the shared `OPEN` sentinel. Filled but not yet
    resolved → return `Resolution(status="open", exit_price=None, r_multiple=None,
    closed_at=None, filled_at=<fill time>)` (still `is_open`).
  - Every closed result produced after a fill carries `filled_at`.
  - Tests: fill on bar 2 then TP on bar 3; fill bar also touches SL → loss; fill bar also
    touches TP only → still open; never touched within `max_fill_bars=3` → `skipped` with
    `closed_at` = third counted bar; gap-across fill; `None` bars not counted; no bars →
    `OPEN` identity; long and short variants.

- [x] **M4 — `resolver.py`: maximum holding time.**
  - Only `files/resolver.py` and `files/tests/test_resolver.py`.
  - `resolve(...)`: add keyword-only `max_hold_bars: Optional[int] = None`. Count counted
    bars starting at the fill bar (fill bar = 1) when `require_fill=True`, otherwise
    starting at the first counted bar.
  - After evaluating SL/TP on counted bar number `max_hold_bars` with no touch: exit at
    that bar's `close` (`getattr(bar, "close", None)`). If `close` is `None`, keep going
    and exit at the first later bar that has a close. `reward`/`gross_r`/`r_multiple` as
    in M2 (cost applies), `status = classify_r(r_multiple)`, `exit_reason="timeout"`,
    `closed_at = bar.bar_time`.
  - Tests: timeout exit in profit → `win`; in loss → `loss`; near zero → `breakeven`;
    SL touch on the timeout bar wins over the timeout; `close=None` defers to next bar;
    `max_hold_bars=None` keeps old behaviour.

- [ ] **M5 — Wire costs, fill and timeout into the live resolver.** *Requires H1.*
  - Check first: `files/schema.sql` contains `gross_r` and `filled_at`. If not → blocked.
  - `files/main.py` config (new): `COST_SPREAD` (float, default `"0.30"`),
    `COST_SLIPPAGE` (float per side, default `"0.05"`), `RESOLVER_REQUIRE_FILL`
    (bool, default `"true"`), `ENTRY_FILL_MAX_BARS` (int, default `"10"`),
    `MAX_HOLD_BARS` (int, default `"240"`). Helper
    `def round_trip_cost() -> Decimal: return Decimal(str(COST_SPREAD)) + 2 * Decimal(str(COST_SLIPPAGE))`.
  - `resolve_open_trades()`: also select `mode`; the bar query also selects
    `(payload->'candle'->>'close')::numeric` and passes it as `PriceBar.close`.
    - `mode == 'live'` (trades typed by the human with `/journal`): call `resolver.resolve`
      exactly as today (no cost, no fill requirement, no timeout).
    - any other mode: pass `cost=round_trip_cost()`, `require_fill=RESOLVER_REQUIRE_FILL`,
      `max_fill_bars=ENTRY_FILL_MAX_BARS`, `max_hold_bars=MAX_HOLD_BARS`.
    - Closed result: the `UPDATE` also sets `gross_r` and `filled_at`. `skipped` results
      are written with `status='skipped'`, `exit_price=NULL`, `r_multiple=NULL`.
    - Still open but `outcome.filled_at` is set: `UPDATE journal SET filled_at = %s
      WHERE id = %s AND filled_at IS NULL`.
  - Tests (`files/tests/test_main.py`): the two existing `test_resolve_open_trades_*`
    tests feed tuple rows through `_FakeConn`; update the fake rows for the extra `mode`
    and `close` columns (intended, list in PR). Add: forward trade closes with net R
    lower than gross R by `cost/risk`; forward trade never filled → `skipped`; live trade
    is resolved without cost; filled-but-open writes `filled_at` only.

- [ ] **M6 — Wire the same options into `backtest.py`.** *Requires H1.*
  - Check first as in M5.
  - `EntryParams`: add with defaults `cost: Decimal = Decimal(0)`,
    `require_fill: bool = False`, `max_fill_bars: Optional[int] = None`,
    `max_hold_bars: Optional[int] = None`. `resolve_trade(...)` gets the same four as
    keyword-only args with those defaults and forwards them to `resolver.resolve`;
    `generate_trades` passes them from `params`.
  - CLI: `--spread` (default env `COST_SPREAD` or 0.30), `--slippage` (default env
    `COST_SLIPPAGE` or 0.05), `--no-fill-model` (flag; default is fill model ON),
    `--max-fill-bars` (default 10), `--max-hold-bars` (default 240). `cost = spread + 2*slippage`.
  - `build_summary`: add `skipped` (status `skipped`), `timeouts`
    (`exit_reason == "timeout"`), `total_gross_r`. `resolved` counts win + loss +
    breakeven. `expectancy = total_r / (generated - skipped - opens)` — note this changes
    the old definition (opens used to count as 0R); update the footnote text in
    `print_summary` and the hand-computed expectation in
    `test_build_summary_hand_computed_numbers` accordingly (intended, list in PR).
    Print the new lines in `print_summary`, including cost settings.
  - `close_backtest_trade` also writes `gross_r` and `filled_at`; `skipped` rows are
    persisted with status `skipped`.
  - Tests (`files/tests/test_backtest.py`): params are forwarded; cost lowers `total_r`
    but not `total_gross_r`; skipped trades are excluded from expectancy; no-pyramiding
    gating still unblocks after a `skipped` trade.

- [ ] **M7 — Record every auto-capture decision, including rejected ones.** *Requires H1.*
  - Check first: `files/schema.sql` contains `capture_outcome`. If not → blocked.
  - Problem: `forward_autocapture` calls Hermes but never calls `save_analysis`, and
    journal rows get `analysis_id=None`. Rejected decisions exist only in JSONL logs.
  - `save_analysis(...)`: add optional `capture_outcome: str | None = None`, insert it,
    add `RETURNING id`, return the `int` id. Existing callers ignore the return value.
  - New sync helpers: `fetch_alert_id(symbol, timeframe, bar_time) -> int | None`
    (exact match on the unique key) and `update_analysis_outcome(analysis_id, outcome)`.
  - New pure function `evaluate_decision(decision: dict | None) -> str` returning the
    first matching outcome, in this order: `"unparsed"` (None), `"no_trade"`,
    `"low_confidence"`, `"incomplete_levels"`, `"bad_levels"`, else `"eligible"`. It
    replaces the inline `if` chain in `forward_autocapture` (same checks, same order).
  - `forward_autocapture` flow after the Hermes call: keep the latency returned by
    `forward_to_hermes`; `alert_id = fetch_alert_id(...)` (replaces the
    `fetch_latest_alert` lookup there); `outcome = evaluate_decision(decision)`;
    `analysis_id = save_analysis({"id": alert_id, "bar_time": bar_time}, symbol,
    timeframe, content, latency, "autocapture", outcome)`. If `outcome != "eligible"`
    → log and return. Else create the journal entry with `analysis_id`, then
    `update_analysis_outcome(analysis_id, "captured")`; on `ForwardTradeExists` →
    `update_analysis_outcome(analysis_id, "duplicate_open")`.
  - All DB helpers go through `asyncio.to_thread`.
  - Tests: extend `_setup_autocapture` to monkeypatch the new helpers; one test per
    outcome asserting the value passed to `save_analysis`; captured path passes the
    returned id to `create_journal_entry` and updates outcome to `captured`; unique
    violation path updates to `duplicate_open`; `evaluate_decision` unit tests;
    `save_analysis` returns the id (fake cursor).

- [ ] **M8 — Do not act on stale decisions.**
  - Config: `FORWARD_MAX_BAR_AGE_S` (float, default `"120"`), `FORWARD_MAX_LATENCY_S`
    (float, default `"90"`).
  - In `forward_autocapture`, before calling Hermes: if
    `(_utcnow() - bar_time).total_seconds() > FORWARD_MAX_BAR_AGE_S` → log and return
    (no Hermes call, no analysis row).
  - After the Hermes call: if latency `> FORWARD_MAX_LATENCY_S`, the outcome saved by M7
    is `"stale_decision"` regardless of the decision, and no journal entry is created.
  - Tests: old bar → Hermes mock not called; slow Hermes (mock returns latency 200) →
    outcome `stale_decision`, no journal; fresh and fast → unchanged behaviour.

- [ ] **M9 — Shadow-journal rejected trades to measure what each filter is worth.**
  - Idea: a decision that had usable levels but was rejected by a gate is journaled with
    `mode='shadow'` and resolved like a forward trade. Comparing average R of `forward`
    vs `shadow` shows whether the gate helps.
  - New `has_open_trade(symbol, timeframe, mode) -> bool`; keep
    `has_open_forward_trade` as a thin wrapper calling it with `"forward"` (tests
    monkeypatch the old name).
  - Config: `SHADOW_CAPTURE` (bool, default `"true"`).
  - In `forward_autocapture`: when `SHADOW_CAPTURE` and the outcome is `low_confidence`
    (or, after later items, any outcome starting with `risk:` or equal to `vetoed`) **and**
    the decision is long/short with complete levels that pass `_levels_sane`, and there
    is no open shadow trade for the symbol/timeframe → `create_journal_entry(..., mode
    "shadow", ..., setup_tags = tags + ["gate:<outcome>"], alert_id, analysis_id)`.
  - `resolve_open_trades`: the `mode IN (...)` filter becomes
    `('live', 'forward', 'shadow', 'mech')` (`mech` is used by D4).
  - `backtest.PROTECTED_MODES`: add `"shadow"` and `"mech"`.
  - Tests: low-confidence with sane levels → shadow entry with the gate tag;
    `no_trade` → none; open shadow exists → none; `SHADOW_CAPTURE=false` → none; the
    resolver query test asserts the new mode list.

## Phase D — make the decision layer consistent and testable

- [ ] **D1 — One output contract, defined once in code.**
  - Problem: the `HERMES_SYSTEM` default in `files/main.py` asks for a compact object,
    while `trading-confluence-orchestrator/SKILL.md` section 13 demands a different, much
    larger one. The model receives both.
  - Add `HERMES_DECISION_KEYS = ("decision", "final_status", "entry", "stop_loss",
    "take_profit", "confidence", "setup_tags", "rationale", "missing_data")`.
  - Rewrite the `HERMES_SYSTEM` default so that it (a) keeps every existing rule,
    (b) adds `"final_status"` = the orchestrator's final status string, (c) states that
    this compact object **replaces** the skill's long Output Contract for this caller
    (see the skill's section 13A), (d) states that `long`/`short` is allowed only when
    `final_status` is `ENTRY_REVIEW` or `COUNTERTREND_REVIEW`, and that it is a paper
    journal proposal, not an order.
  - `parse_hermes_decision`: also return `final_status` (upper-cased string or `None`)
    and `rationale` (string or `""`). If `decision` is long/short and `final_status` is
    present but not one of the two review statuses → set `decision` to `"no_trade"` and
    add key `"status_conflict": True` (else `False`).
  - `evaluate_decision` (from M7): return `"status_conflict"` before the `no_trade`
    check when that flag is true.
  - Tests: `test_hermes_system_mentions_every_contract_key`; parse tests for
    `final_status` present/absent/conflicting. Existing parse tests that compare the
    whole returned dict need the new keys added to their expected dicts (intended).

- [ ] **D2 — Make the orchestrator skill agree with D1 and stop dead-ending.**
  - File: `hermes-config/skills/trading/trading-confluence-orchestrator/SKILL.md` only
    (plus one new test file). Bump `version:` to `0.2.0`; keep `name:` unchanged.
  - Add section **"11A. Default strategy record"** — used when the caller supplies no
    Strategy Catalog (the forwarder never does): `Strategy_ID: XAU-CONFLUENCE-V1`,
    status `Paper_Analysis`; allowed regimes `Trend_Up`, `Trend_Down`; `Transition` only
    via the countertrend protocol; `Range`/`Unknown` → at most `WATCH`; required
    confluences: valid trade location + structural event + structural invalidation + M5
    and M15 `mtf` bias not both opposing; minimum R:R 1.5; minimum confluence score 65;
    `Maximum_Signal_Age_Minutes: 2`; news status `Unknown` is acceptable because the
    forwarder enforces news blackouts. State in section 5 step 1 that this record
    applies instead of returning `INSUFFICIENT_DATA` for a missing catalog.
  - Add section **"13A. Compact forwarder contract"**: when the system prompt asks for
    the compact object, return it **instead of** section 13. List all nine keys from
    `HERMES_DECISION_KEYS` and the mapping: `decision` = `long`/`short` only for
    `ENTRY_REVIEW`/`COUNTERTREND_REVIEW` with direction buy/sell, otherwise `no_trade`;
    `entry` = midpoint of the entry zone; `stop_loss` = invalidation price;
    `take_profit` = target 1; `confidence` = confluence score / 100; `setup_tags` =
    confluence tags; `rationale` = reasoning summary (max 300 characters);
    `missing_data` as today. Add one sentence to section 0 that this proposal is a paper
    journal record for human review, not an order command.
  - New `files/tests/test_skill_contract.py`: locate the file with
    `Path(__file__).resolve().parents[2] / "hermes-config/skills/trading/trading-confluence-orchestrator/SKILL.md"`;
    assert the 13A section exists and contains every key in `main.HERMES_DECISION_KEYS`;
    assert `XAU-CONFLUENCE-V1` appears; assert frontmatter `name:` is unchanged.

- [x] **D3 — Extract the mechanical entry rule into a pure `files/strategy.py`.**
  - Pure refactor, no behaviour change. Model the module on `resolver.py` (no env, no
    DB, no FastAPI).
  - Move from `backtest.py` to `strategy.py`: `EntryParams`, `resolve_direction`,
    `compute_levels`. In `backtest.py` re-import them
    (`from strategy import EntryParams, resolve_direction, compute_levels`) so
    `backtest.EntryParams` etc. still resolve and `test_backtest.py` passes untouched.
  - Add to `strategy.py`: a `BarLike` protocol (`close`, `atr`, `triggers`,
    `structure_trend`, `swing_high`, `swing_low`); `@dataclass(frozen=True) Proposal`
    (`direction`, `entry`, `stop_loss`, `take_profit`);
    `def propose(bar, params) -> tuple[Optional[Proposal], Optional[str]]` returning the
    proposal or the skip reason (`"no_trigger"`, `"trigger_filter"`, `"no_direction"`,
    `"bad_levels"`) using exactly the guard order now inside
    `backtest.generate_trades`; and `def bar_from_payload(payload: dict)` building a
    frozen dataclass from a webhook payload (`candle.close`, `candle.atr`, `triggers`,
    `smc.structure_trend`, `smc.swing_high`, `smc.swing_low`; numbers via
    `Decimal(str(x))`, missing → `None`).
  - `backtest.generate_trades` calls `propose(...)` instead of its inline guards.
  - New `files/tests/test_strategy.py`: `propose` skip reasons and happy paths (long,
    short, swing mode); `bar_from_payload` with full and sparse payloads.

- [ ] **D4 — Live mechanical baseline (`mode='mech'`), directly comparable to the backtest.**
  - Config: `MECH_CAPTURE` (bool, default `"false"`), `MECH_TRIGGERS` (comma list,
    default empty = any), `MECH_SL_ATR` (`"1.5"`), `MECH_RR` (`"2.0"`),
    `MECH_USE_SWING` (bool, `"false"`). Build one `strategy.EntryParams` from them with
    `direction_override="auto"`.
  - New `async def mech_autocapture(payload, bar_time)`: return if `MECH_CAPTURE` is
    off or symbol/timeframe is not `DEFAULT_SYMBOL`/`DEFAULT_TF`; `proposal, reason =
    strategy.propose(strategy.bar_from_payload(payload), params)`; no proposal → debug
    log and return; `has_open_trade(symbol, tf, "mech")` → return; create the journal
    entry with mode `"mech"`, tags = the payload triggers, `alert_id` from
    `fetch_alert_id`. Whole body in `try/except Exception` that logs and swallows, like
    `forward_autocapture`. No Hermes call.
  - `ingest_signal`: when the alert was inserted, `await mech_autocapture(...)` before
    `forward_autocapture(...)`; a failure in one must not prevent the other.
  - Tests: off by default; qualifying bullish bar → one `mech` entry with ATR levels;
    no trigger → none; open mech trade → none; exception swallowed; `ingest_signal`
    calls both.

- [ ] **D5 — Optional veto mode: rules propose, the LLM only approves or rejects.**
  - Do this last in phase D, only after D4 has been running.
  - Config: `FORWARD_DECISION_SOURCE` (`"hermes"` default, or `"mechanical_veto"`).
    `"hermes"` = today's behaviour, untouched.
  - `forward_to_hermes(payload, received_at, extra_user_text: str = "")`: append the
    extra text to the user message when non-empty.
  - In `forward_autocapture` when the source is `mechanical_veto`: compute the mechanical
    proposal (same params as D4) **before** calling Hermes; no proposal → return without
    a Hermes call. Otherwise call Hermes with `extra_user_text` = one line stating the
    proposed direction/entry/stop/target and asking it to return the compact contract
    with `decision` equal to that direction only if the confluence rules support it,
    else `no_trade`. Approved = decision equals the proposal direction and confidence ≥
    `FORWARD_MIN_CONFIDENCE`. Approved → forward journal entry using the **mechanical**
    levels (ignore Hermes's levels). Not approved → outcome `"vetoed"`; M9 then shadows
    it with the mechanical levels.
  - Tests: default source unchanged; no proposal → Hermes not called; approve → forward
    entry with mechanical levels; reject → `vetoed` and a shadow entry.

## Phase R — risk controls (all gates run inside `forward_autocapture`)

- [ ] **R1 — Pure risk gate for every proposed trade.**
  - Config: `FORWARD_MIN_RR` (`"1.5"`), `FORWARD_MIN_SL_ATR` (`"0.5"`),
    `FORWARD_MAX_SL_ATR` (`"5.0"`), `FORWARD_MIN_SL_COST_MULT` (`"5.0"`),
    `FORWARD_MAX_ENTRY_DIST_ATR` (`"1.0"`), `FORWARD_SESSIONS`
    (comma list, default `"london,overlap,newyork"`; empty = all sessions).
  - New pure `risk_gate(direction, entry, stop_loss, take_profit, atr, close) -> str | None`
    returning the first failing reason or `None`: `"rr_too_low"`
    (`abs(tp-entry)/abs(entry-sl) < FORWARD_MIN_RR`), `"sl_too_tight"` /
    `"sl_too_wide"` (stop distance vs `atr` × the two multipliers), `"sl_inside_cost"`
    (stop distance `< FORWARD_MIN_SL_COST_MULT × float(round_trip_cost())`),
    `"entry_too_far"` (`abs(entry-close) > FORWARD_MAX_ENTRY_DIST_ATR × atr`). `atr` and
    `close` come from `payload["candle"]`.
  - New pure `session_allowed(session: str | None) -> bool`: `True` when the list is
    empty or `session` is `None` (schema 2.0), else membership.
  - Wiring: session check happens **before** the Hermes call (blocked → log, return, no
    Hermes call). `risk_gate` runs after the decision is `eligible`; a failure makes the
    outcome `"risk:<reason>"` (saved via M7, shadowed via M9), no forward entry.
  - Tests: one per reason at and around its boundary; session cases; wiring tests for
    blocked session (Hermes not called) and a `risk:rr_too_low` outcome.

- [ ] **R2 — Daily stop and trade cap.**
  - Config: `FORWARD_DAILY_MAX_LOSS_R` (`"3.0"`), `FORWARD_MAX_TRADES_PER_DAY` (`"10"`).
  - New sync `forward_day_stats(symbol, day_start) -> dict` with `closed_r` (sum of
    `r_multiple` for `mode='forward'` rows with `closed_at >= day_start`, 0 if none) and
    `trades` (count of `mode='forward'` rows with `opened_at >= day_start` and
    `status <> 'skipped'`). `day_start` = today 00:00 UTC from `_utcnow()`.
  - New pure `daily_limit_reason(stats) -> str | None`: `"daily_loss_limit"` when
    `closed_r <= -FORWARD_DAILY_MAX_LOSS_R`, `"daily_trade_cap"` when
    `trades >= FORWARD_MAX_TRADES_PER_DAY`.
  - Wiring: checked before the Hermes call; a reason → log at INFO and return.
  - Tests: pure function boundaries; SQL helper with the fake pool; wiring (Hermes not
    called when a limit is hit).

- [ ] **R3 — News blackout windows.**
  - Config: `NEWS_BLACKOUTS` (comma-separated UTC ISO timestamps such as
    `2026-12-04T13:30Z`, default empty), `NEWS_BLACKOUT_MIN` (`"15"`).
  - New pure `parse_blackouts(raw: str) -> list[datetime]` (accept a trailing `Z`,
    require timezone-aware results, silently drop malformed entries and return the rest)
    and `in_news_blackout(now, events, window_min) -> bool` (true when `now` is within
    ± `window_min` minutes of any event). Parse once at import into `NEWS_EVENTS`.
  - Wiring: checked before the Hermes call using `_utcnow()`; in blackout → log, return.
  - Tests: parser (valid, `Z` suffix, malformed, empty); window edges; wiring.
  - Note for the owner: the list is maintained by hand in Railway (NFP, CPI, FOMC).

- [ ] **R4 — Telegram notifications with a suggested position size.**
  - Config: `NOTIFY_FORWARD` (bool, `"true"`), `ACCOUNT_BALANCE` (float, default unset),
    `RISK_PCT` (`"1.0"`), `CONTRACT_SIZE` (`"100"`, ounces per lot), `LOT_STEP` (`"0.01"`).
  - New pure `suggest_lots(balance, risk_pct, stop_distance, contract_size, lot_step)
    -> float | None`: `None` when balance is unset or `stop_distance <= 0`; else
    `balance × risk_pct/100 ÷ (stop_distance × contract_size)` rounded **down** to the
    lot step.
  - New `async def notify(text: str)`: `tg_send(chat_id, text, parse_mode="HTML")` for
    every id in `TG_ALLOWED`; never raises.
  - On a captured forward trade: send direction, entry, stop, target, R:R, confidence,
    tags, suggested lots (or "-" when unset) and the line
    "Saran paper — keputusan tetap manual". All dynamic text through `html.escape`.
  - Split `resolve_open_trades` into `resolve_open_trades_detailed() -> list[dict]`
    (id, mode, direction, status, exit_price, r_multiple, exit_reason) and keep
    `resolve_open_trades()` returning `len(...)` so existing tests pass. `_resolve_job`
    uses the detailed version and notifies once per closed `forward` trade.
  - Tests: `suggest_lots` rounding and `None` cases; capture sends one message per
    allowed chat (mock `tg_send`); `NOTIFY_FORWARD=false` sends nothing; resolve job
    notifies for forward only.

## Phase P — reporting and polish

- [ ] **P1 — `/stats` Telegram command.**
  - New sync `fetch_closed_r(symbol, mode, limit=5000) -> list[tuple[str, Decimal]]`
    (status, r_multiple) for closed rows (`win`/`loss`/`breakeven`) ordered by
    `closed_at`. New pure `summarize_r(rows) -> dict`: `n`, wins, losses, breakevens,
    `win_rate`, `avg_r`, `total_r`, `max_consecutive_losses`, `max_drawdown_r` (largest
    peak-to-trough drop of the cumulative R curve).
  - New sync `capture_outcome_counts(days=7) -> list[tuple[str, int]]` from `analyses`
    (requires H1; if the column is missing in `files/schema.sql`, leave this part out
    and say so in the PR).
  - `/stats [mode]`: with no argument show one block per mode in
    `("forward", "shadow", "mech", "live")`, then the outcome counts. Add the line
    "⚠️ sampel < 100 trade, belum signifikan" for any mode with `n < 100`.
  - `/trades`: the stats line shows `forward` as well as `live`.
  - Tests: `summarize_r` hand-computed (including drawdown and streak); command output
    contains each mode and the small-sample warning (mock DB helpers and `tg_send`).

- [x] **P2 — Do not lose an alert whose DB save failed.** *(low priority)*
  - Problem: `already_seen()` records the `event_id` in the webhook before the
    background `save_alert` runs. If the save fails, a replay of the same alert is
    dropped as a duplicate.
  - Add `forget_event(event_id)` (remove from `_seen` if present). In `ingest_signal`
    wrap `save_alert` in `try/except Exception`: on failure call `forget_event`,
    `append_jsonl("errors", {...})` with the event id and `repr(e)`, `log.exception`,
    and return without re-raising.
  - Tests: failed save → event forgotten, error logged, `forward_autocapture` not
    called; a second webhook with the same `event_id` is then accepted.

<!--
Format: each checkbox is one PR-sized task; the indented bullets are its spec.
Avoid: anything touching .github/workflows/, .claude/, CLAUDE.md, .env*, or adding
new runtime dependencies to files/requirements.txt without justification in the PR.
-->
