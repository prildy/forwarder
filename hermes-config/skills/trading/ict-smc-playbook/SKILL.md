---
name: ict-smc-playbook
description: Read the liquidity_pools and smc blocks of the XAUUSD TradingView payload with a staged ICT/SMC framework - liquidity, sweep, BOS/CHoCH, order block, fair value gap - for paper-only decision support. Maps structure and location; never executes broker actions.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, ict, smc, liquidity, sweep, choch, fvg, order-block, xauusd, paper-trading]
    category: trading
---

# ICT / SMC Playbook v0.2.0

Paper analysis only; no broker execution; payload facts only. The shared safety rules,
the payload overview and the final output format are in
`trading-confluence-orchestrator` (sections 0, 2 and 9) and apply here.

**Role:** liquidity map, sweep classification, structure state, and the order-block and
FVG locations. It provides location and invalidation levels; it does not time entries.

Scope of this version: liquidity, sweep, BOS/CHoCH, FVG, order block. Kill zones, Judas
swing, OTE, breaker and mitigation blocks are out of scope; do not use those labels.

## 1. `liquidity_pools` — what each field means

Levels are chart-timeframe pivot highs/lows (pivot length 10), up to 20 stored per side.
A level is removed once price trades through it.

| Field | Exact definition |
|---|---|
| `bsl_nearest` / `ssl_nearest` | Nearest stored pivot high above / pivot low below the close; `null` if none |
| `bsl_dist_atr` / `ssl_dist_atr` | Distance from close in ATRs |
| `bsl_pool_size` / `ssl_pool_size` | Number of stored levels within 0.15 × ATR of the nearest one. ≥ 2 means equal highs/lows |
| `bsl_swept` / `ssl_swept` | **This bar** traded through a stored level and **closed back** inside. A liquidity grab |
| `bsl_swept_level` / `ssl_swept_level` | The most extreme level swept on this bar |
| `bsl_taken` / `ssl_taken` | **This bar closed beyond** a stored level. A break, not a grab |
| `active_bsl` / `active_ssl` | Count of stored levels |
| `previous_day_high` / `previous_day_low` | Prior daily bar's high / low |
| `session_high` / `session_low` | Running extreme of the current session so far |

Not available: pool ids, touch counts, zone widths, higher-timeframe pools, or whether a
level was swept on an earlier bar.

## 2. `smc` — what each field means

| Field | Exact definition | Caveat |
|---|---|---|
| `swing_high` / `swing_low` | Last confirmed pivot high / low (length `swing_len`) | Chart timeframe |
| `structure_trend` | `bullish` after the last close above a swing high, `bearish` after the last close below a swing low | Persistent |
| `structure_event` | `bos_*` when the break continues `structure_trend`, `choch_*` when it flips it | Only on the break bar; needs a close, not a wick |
| `structure_scope` | `external` when the swing range exceeds 3 × ATR, else `internal` | A size heuristic, **not** higher-timeframe structure |
| `pd_zone`, `equilibrium` | `premium` / `discount` / `equilibrium` relative to the midpoint of the last swing range (±5%) | Chart-timeframe range |
| `bull_ob_top/bottom` | The candle with the lowest low between the broken swing high and the break bar | One stored OB per side; replaced at each new break |
| `bull_ob_freshness`, `bull_ob_mitigated` | `mitigated` only after a **close below** the OB bottom | So `mitigated` really means **broken**; `fresh` means not broken, it may have been touched many times |
| `in_bull_ob` | This bar's range overlaps the unbroken OB | Bar-only |
| `bull_ob_displacement`, `bear_ob_displacement` | Constant strings | **Not evidence. Ignore.** |
| `bull_fvg_top/bottom` | Latest three-candle bullish gap (`low > high[2]`) | Only the latest gap per side |
| `bull_fvg_status`, `bull_fvg_filled` | `full_fill` once a low reaches the gap bottom; else `fresh` | `fresh` includes partially filled |
| `bear_*` | Mirror definitions | |

## 3. Vocabulary

- **Buy-side liquidity (BSL)**: resting orders above highs. **Sell-side (SSL)**: below lows.
- **Sweep / grab**: trade through a level, close back. Outcome unknown until price reacts.
- **Run / taken**: close beyond the level. Liquidity became fuel for continuation.
- **BOS**: confirmed close beyond a swing in the direction of structure.
- **CHoCH**: confirmed close beyond a swing against structure; an early shift, not an entry.
- **Order block / FVG**: a location to react from, never an entry by itself and never a
  level price "must" return to.

## 4. Reading procedure

1. **Map liquidity.** State nearest BSL and SSL with their ATR distance and pool size.
   Liquidity is a possible draw; never write that price "must" take it.
2. **Classify this bar's liquidity event.**

   | Payload | Classification |
   |---|---|
   | `ssl_swept` true | Sell-side grab; bullish reaction **candidate** |
   | `bsl_swept` true | Buy-side grab; bearish reaction **candidate** |
   | `ssl_taken` / `bsl_taken` true | Liquidity run in that direction; continuation evidence |
   | Low below `previous_day_low` or `session_low` and close above it | Sweep of a day/session level (derived) |
   | none | No event |

   A grab is confirmed as a reversal only by structure (a later CHoCH). That later bar is
   a different payload; on the sweep bar the outcome is `unresolved`.
3. **Read structure.** `structure_trend` is the working direction. `structure_event` on
   this bar is fresh evidence. `structure_scope` only grades the size of the swing.
4. **Locations for direction `D`** (long shown; mirror for short):
   - Order block: `in_bull_ob` true and `bull_ob_freshness` is `fresh`.
   - FVG: `bull_fvg_status` is `fresh`, `candle.low <= bull_fvg_top`,
     `candle.high >= bull_fvg_bottom`.
   - Sweep: `ssl_swept`, or the derived day/session sweep.
   A bullish OB or FVG while `structure_trend` is `bearish` is a conflict, not a location.
5. **Invalidation level** for the location used: `bull_ob_bottom`, `bull_fvg_bottom`, the
   sweep bar's `candle.low`; fallback `swing_low`.
6. **Status.**

| Situation | Status |
|---|---|
| No location on the `D` side | `WATCH` |
| Location present, `structure_trend` = `D` | `REVIEW` (continuation) |
| Sweep in favour of the higher-timeframe bias with a close back | `REVIEW` (sweep with trend) |
| Sweep against the higher-timeframe bias | `COUNTERTREND_CANDIDATE` (orchestrator section 7) |
| Location present, `structure_trend` opposite | `WAIT` |
| `structure_event` against `D` on this bar, or the OB just broke (`mitigated`) | `INVALIDATED` |

## 5. Conflicts to report

- Sweep with no reaction evidence; sweep bar that also closes weak.
- `*_taken` in the direction opposite to `D` on this bar.
- OB/FVG direction against `structure_trend`.
- `structure_scope` is `internal` for a countertrend idea.
- Target (`bsl_nearest` for longs) closer than the stop distance.

## 6. Findings (only when this skill is used on its own)

```json
{
  "skill": "ict-smc-playbook",
  "status": "WATCH|WAIT|REVIEW|COUNTERTREND_CANDIDATE|INVALIDATED",
  "direction": "long|short|null",
  "location": "ob|fvg|sweep|day_level|none",
  "invalidation_level": null,
  "facts": ["string"],
  "conflicts": ["string"],
  "missing_data": ["string"]
}
```

## 7. Common mistakes

- Calling `structure_scope: external` higher-timeframe structure.
- Reading `mitigated` as "touched once"; it means closed through.
- Using `*_ob_displacement` as evidence.
- Treating every sweep as a reversal, or every break as continuation without a close.
- Assuming a sweep happened earlier because an OB or CHoCH exists now.
- Saying price must fill an FVG or take a pool.
