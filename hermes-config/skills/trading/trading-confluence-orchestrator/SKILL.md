---
name: trading-confluence-orchestrator
description: Final synthesis layer for XAUUSD paper decision support. Applies the data and risk gates, combines the BBMA, ICT/SMC, price-action, Ichimoku and momentum skills against the real TradingView payload, and returns one compact JSON decision for the forwarder.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, confluence, orchestrator, paper-trading, xauusd, risk-gate]
    category: trading
---

# Trading Confluence Orchestrator v0.2.0

## 0. Mode and safety rules (shared by all trading skills)

```text
MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

- A `long` / `short` decision is a **paper journal proposal for human review**, never an
  order. Never output lot size, a guaranteed outcome, or a win probability.
- Every price and state you cite must come from the payload. Never invent a level, a
  zone, a sweep, a prior bar, news, or a higher-timeframe structure.
- One payload describes **one closed bar**. Multi-bar sequences (sweep, then structure
  shift, then retest) cannot be confirmed unless a persistent field records them (see
  section 2). When a rule needs history the payload does not carry, say so in
  `missing_data` and downgrade; do not assume the sequence happened.
- Never hide a conflict between skills. Never let several indicator confirmations replace
  a missing location, a missing invalidation level, or a failed gate.
- Do not change rules, thresholds or parameters yourself.

The five specialist skills (`bbma`, `ict-smc-playbook`,
`supply-demand-price-action-playbook`, `ichimoku-filter-playbook`,
`momentum-filter-stochrsi-adx-di`) define how to read their own payload blocks. When this
orchestrator is in use, they produce findings for it; only this skill produces output.

## 1. Who decides what

| Skill | Payload blocks | Role | Cannot decide alone |
|---|---|---|---|
| ICT/SMC | `liquidity_pools`, `smc` | Liquidity, sweep, structure, OB, FVG | Direction without reaction |
| Price action | `candle`, `smc`, `liquidity_pools` | Location quality, candle reaction, invalidation | Entry without timing and risk |
| BBMA | `bbma` | Timing: Extreme, Reentry, CSM | Direction or location |
| Ichimoku | `ichimoku`, `mtf.*.cloud_bias` | Regime filter | Anything; filter only |
| Momentum | `adx_di`, `stoch_rsi`, `macd`, `vw_trend`, `mtf.*.adx*` | Strength and timing filter | Anything; filter only |
| Orchestrator | all | Gates, conflicts, levels, final output | Broker execution |

## 2. The payload as it really is

Top level: `schema`, `event_id`, `symbol`, `ticker`, `timeframe` (the chart timeframe,
for example `30S`), `bar_time` (UTC, bar open), `bar_confirmed`, `session`, `mtf`,
`triggers`, then the blocks `candle`, `bbma`, `ichimoku`, `liquidity_pools`, `vw_trend`,
`smc`, `adx_di`, `stoch_rsi`, `momentum_filter`, `macd`.

- **Every block except `mtf` is computed on the chart timeframe.** Swings, order blocks,
  FVGs and liquidity levels are chart-timeframe objects, not higher-timeframe zones.
- `mtf.m1`, `mtf.m5`, `mtf.m15` each carry only `ema50_bias`, `cloud_bias`, `di_bias`
  (`bullish|bearish|neutral`), `adx`, and `adx_state` (`trending` when ADX ≥ 20, else
  `ranging`). Values come from the still-forming higher-timeframe bar.
- `session` (UTC): `asia` 00–07, `london` 07–12, `overlap` 12–16, `newyork` 16–21, `off`.
- `candle`: `open high low close`, `volume` (tick volume; weak evidence),
  `volume_state` (`spike` > 1.5× 20-bar average, `low` < 0.6×, `normal`, `unavailable`),
  `pattern` (`bullish_engulfing|bearish_engulfing|bullish_pin|bearish_pin|none`), `atr`.
- `triggers` lists events on this bar: `smc_bos_*`, `smc_choch_*`, `smc_fvg_*`,
  `liq_bsl_sweep`, `liq_ssl_sweep`, `bbma_extreme_*`, `bbma_csm_*`, `bbma_reentry_*`,
  `ichi_tk_cross_*`, `vwt_flip_*`, `di_cross_*`, `stochrsi_*`, `macd_div_*`. A trigger is
  a reason to analyse, not a reason to trade.

**Not in the payload, never claim them:** news or calendar status, spread, open
positions, M3 data, higher-timeframe structure or zones, anything about earlier bars
beyond the persistent fields below.

**Persistent fields (carry history):** `smc.structure_trend`, the stored order blocks and
FVGs in `smc`, `smc.swing_high/low`, `bbma.reentry_state`, `bbma.bars_since_*`,
`vw_trend.bars_in_trend`, `macd.divergence_last` + `divergence_bars_ago`.
**Bar-only fields (true only on the event bar):** `smc.structure_event`,
`liquidity_pools.*_swept`, `*_taken`, `bbma.extreme_*`, `bbma.csm_*`,
`bbma.reentry_buy/sell`, all crosses.

## 3. Final status vocabulary

| `final_status` | Meaning | `decision` |
|---|---|---|
| `DATA_ERROR` | Gate 1 failed | `no_trade` |
| `INSUFFICIENT_DATA` | A critical field is absent or null | `no_trade` |
| `NO_TRADE` | Valid data, but a hard rule or the risk gate fails | `no_trade` |
| `WATCH` | Context developing, no location or no reaction yet | `no_trade` |
| `WAIT` | Location present, timing or confirmation incomplete | `no_trade` |
| `TAKE_PROFIT_REVIEW` | CSM or target reached in trend direction; do not chase | `no_trade` |
| `INVALIDATED` | The stored OB/structure for the idea is broken | `no_trade` |
| `ENTRY_REVIEW` | All gates pass, with higher-timeframe bias | `long` / `short` |
| `COUNTERTREND_REVIEW` | Section 7 protocol fully passes | `long` / `short` |

## 4. Default strategy record

No Strategy Catalog is supplied by the caller. Use this record; never return
`INSUFFICIENT_DATA` because a catalog is missing.

```text
Strategy_ID: XAU-CONFLUENCE-V1        Status: Paper_Analysis
Higher-timeframe bias: required with the trade, or section 7 applies
Required: valid location + structure support + invalidation level + timing
Minimum R:R to the nearest opposing level: 1.5   (countertrend: 2.0)
Minimum stop distance: 0.5 x candle.atr
Minimum confluence score: 65 / 100
News: unknown to this skill; the forwarder enforces news blackouts
```

## 5. Decision workflow

Work through the steps in order. Stop at the first hard failure.

**Step 1 — Data gate.** `DATA_ERROR` if `bar_confirmed` is not `true`, or `candle`
is missing, or `candle.atr` is null or ≤ 0. `INSUFFICIENT_DATA` if `mtf`, `smc` or
`liquidity_pools` is missing.

**Step 2 — Higher-timeframe bias** (from `mtf` only; the chart timeframe never sets bias).
- `bullish`: `m15.ema50_bias` and `m5.ema50_bias` are both `bullish`, and neither
  `cloud_bias` is `bearish`. `bearish`: the mirror. Otherwise `mixed`.
- Regime: `trend` if `m5.adx_state` or `m15.adx_state` is `trending`; else `range`.
- With `mixed` bias the best possible status is `WAIT`.

**Step 3 — Candidate direction `D`.** Take `D` from the higher-timeframe bias. Consider
the opposite direction only through section 7.

**Step 4 — Location** (at least one, on the `D` side; details in the ICT/SMC and
price-action skills). For `D = long` (mirror for short):
- `smc.in_bull_ob` is `true` and `bull_ob_freshness` is `fresh`.
- The bar overlaps an unfilled bullish FVG: `bull_fvg_status` is `fresh`,
  `candle.low <= bull_fvg_top` and `candle.high >= bull_fvg_bottom`.
- `liquidity_pools.ssl_swept` is `true` (wick below a sell-side level, close back above).
- The bar swept `previous_day_low` or `session_low`: `candle.low` below it and
  `candle.close` above it.

No location → `WATCH`. `smc.pd_zone` (`discount` for longs, `premium` for shorts) improves
quality but is not a location by itself.

**Step 5 — Structure.** `smc.structure_trend` must equal `D` for `ENTRY_REVIEW`. If it is
opposite → `WAIT` (or section 7). One exception: when the location is a sweep in favour
of the higher-timeframe bias (`sweep_with_trend`), an opposite `structure_trend` is
allowed as a pullback; it then scores 0 structure points and is listed as a conflict. `structure_event` in direction `D` on this bar is extra
support; in the opposite direction it is a hard conflict → `NO_TRADE`.

**Step 6 — Timing** (at least one, in direction `D`): `bbma.reentry_buy` / `reentry_sell`;
`stoch_rsi.cross` or a `*_reset` state; `candle.pattern`. None → `WAIT`.
If `bbma.csm_state` equals `D` on this bar → `TAKE_PROFIT_REVIEW` (never chase).

**Step 7 — Filters.** Collect `SUPPORT / NEUTRAL / CONFLICT` from the Ichimoku and
momentum skills. Both in `CONFLICT` → `WAIT`. One in conflict → allowed, list it.

**Step 8 — Levels** (all numbers from the payload, section 6). No valid stop on the
correct side → `NO_TRADE`.

**Step 9 — Risk gate.** R:R below the minimum → `NO_TRADE` (`target_blocked`). Stop
distance below 0.5 × ATR after the fallback in section 6 → `NO_TRADE` (`stop_too_tight`).

**Step 10 — Score** (section 8). Below 65 → `WAIT`. Otherwise `ENTRY_REVIEW`.

## 6. Entry, stop and target

- **Entry** = `candle.close`.
- **Stop** for long, by the location used: order block → `smc.bull_ob_bottom`; FVG →
  `smc.bull_fvg_bottom`; sweep → `candle.low`. If the stop is closer than 0.5 × ATR, use
  `smc.swing_low` when it is lower than that stop. Shorts mirror with `bear_ob_top`,
  `bear_fvg_top`, `candle.high`, `smc.swing_high`. The stop must be below entry for a
  long and above it for a short.
- **Target** = the nearest level beyond entry among: `liquidity_pools.bsl_nearest`,
  `smc.swing_high`, `previous_day_high`, `session_high` (long); `ssl_nearest`,
  `swing_low`, `previous_day_low`, `session_low` (short). Do not skip the nearest level to
  reach a farther one: if R:R to the nearest is too low, the target is blocked.
- **R:R** = |target − entry| ÷ |entry − stop|.

## 7. Countertrend protocol

`D` opposite to the higher-timeframe bias may reach `COUNTERTREND_REVIEW` only if **all**
hold on this bar; otherwise `WATCH`:

1. A sweep against the old direction of a significant level: pool size ≥ 2
   (`bsl_pool_size` / `ssl_pool_size`), or the previous-day or session extreme.
2. A reaction in direction `D`: `candle.pattern` in `D`, or `structure_event` CHoCH in `D`.
3. Exhaustion evidence: `macd.divergence_last` is `regular_<D>` with
   `divergence_bars_ago` ≤ 30, or a BBMA Extreme on the swept side with
   `bars_since_extreme` ≤ 10.
4. `mtf.m1.ema50_bias` or `mtf.m1.di_bias` equals `D`.
5. Stop = the sweep bar's extreme (`candle.low` / `candle.high`); R:R ≥ 2.0.

## 8. Confluence score (checklist, not probability)

| Component | Points |
|---|---:|
| Confirmed bar, data complete | 10 |
| Higher-timeframe bias: m5 + m15 `ema50_bias` with `D` (10); both `cloud_bias` with `D` (+5) | 15 |
| Location: fresh OB 15, FVG 12, sweep 12; favourable `pd_zone` +5; pool ≥ 2 or day/session level +3 | max 20 |
| Structure: `structure_trend` = `D` 12; `structure_scope` external +4; event in `D` this bar +4 | 20 |
| BBMA timing: reentry in `D` 6; `reentry_state` second or continuation +4 | 10 |
| Ichimoku filter: SUPPORT 8, NEUTRAL 4, CONFLICT 0 | 8 |
| Momentum filter: SUPPORT 7, NEUTRAL 3, CONFLICT 0 | 7 |
| Risk: R:R ≥ 2.0 → 10; 1.5–1.99 → 6 | 10 |

`confidence` = score ÷ 100. It measures checklist completeness only. A score never
overrides a failed gate.

## 9. Compact forwarder contract

Return **one JSON object and nothing else**: no prose, no Markdown fences. If the
caller's system prompt lists an exact key set, use that set; otherwise use these keys:

```json
{
  "decision": "long|short|no_trade",
  "final_status": "one value from section 3",
  "entry": null,
  "stop_loss": null,
  "take_profit": null,
  "confidence": 0.0,
  "setup_tags": ["string"],
  "rationale": "string, max 300 characters",
  "missing_data": ["string"]
}
```

- `decision` is `long` / `short` only for `ENTRY_REVIEW` or `COUNTERTREND_REVIEW`;
  then `entry`, `stop_loss`, `take_profit` are numbers per section 6 (long:
  stop < entry < target; short: target < entry < stop). Otherwise all three are `null`.
- `setup_tags`: always include `orch-0.2.0`, the setup (`continuation`, `sweep_with_trend`
  or `countertrend`), the location (`ob`, `fvg`, `sweep`, `day_level`), the timing used,
  and one `conflict:<name>` tag per unresolved conflict.
- `rationale`: the gate that decided the status, then the main evidence and conflict.
- `missing_data`: every field you needed and did not have.

## 10. Common mistakes

- Treating a trigger as a trade. Treating confidence as win probability.
- Taking bias from the chart timeframe instead of `mtf`.
- Reading a sequence across bars that the payload cannot show.
- Averaging conflicts away, or letting filters outvote a missing location or stop.
- Proposing a new entry on a CSM bar. Skipping the nearest opposing level to make R:R work.
