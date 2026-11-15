---
name: supply-demand-price-action-playbook
description: Judge trade location quality, candle reaction, market regime and structural invalidation from the candle, smc and liquidity_pools blocks of the XAUUSD TradingView payload, for paper-only decision support. Never executes broker actions.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, supply-demand, price-action, market-structure, xauusd, paper-trading]
    category: trading
---

# Supply-Demand & Price Action Playbook v0.2.0

Paper analysis only; no broker execution; payload facts only. The shared safety rules,
the payload overview and the final output format are in
`trading-confluence-orchestrator` (sections 0, 2 and 9) and apply here.

**Role:** answer four questions. Is price at a meaningful location? Did it react there?
What is the regime? Where is the idea wrong (invalidation)?

## 1. What this payload offers as "zones"

The payload has **no supply/demand zone records** (no base, no touch count, no zone id).
The usable locations are the ones the ICT/SMC skill defines; treat them as zones:

| Zone type | Fields | Demand or supply |
|---|---|---|
| Bullish order block | `smc.bull_ob_top/bottom`, `bull_ob_freshness`, `in_bull_ob` | Demand |
| Bearish order block | `smc.bear_ob_top/bottom`, `bear_ob_freshness`, `in_bear_ob` | Supply |
| Bullish / bearish FVG | `smc.bull_fvg_*`, `smc.bear_fvg_*` | Demand / supply |
| Swept level | `liquidity_pools.*_swept`, `*_swept_level` | Reaction point |
| Day / session level | `previous_day_high/low`, `session_high/low` | Support / resistance |
| Range position | `smc.pd_zone`, `equilibrium` | Quality modifier only |

Do not invent other zones. Do not call a zone "fresh, first touch": the payload cannot
count touches (`fresh` only means not closed through).

## 2. Regime

| Regime | Payload condition |
|---|---|
| `bullish_trend` | Higher-timeframe bias bullish (orchestrator step 2) and `smc.structure_trend` bullish |
| `bearish_trend` | The mirror |
| `transition` | Higher-timeframe bias and `structure_trend` disagree, or a CHoCH on this bar |
| `range` | `mtf.m5.adx_state` and `mtf.m15.adx_state` both `ranging` and bias `mixed` |
| `unknown` | `structure_trend` is `undefined` or `mtf` missing |

Continuation ideas need a trend regime. In `range` or `transition` the best status from
this skill is `WAIT`.

## 3. Reaction at the location

`candle.pattern` comes from a deterministic detector:

| Value | Definition |
|---|---|
| `bullish_engulfing` / `bearish_engulfing` | Body engulfs the prior opposite body |
| `bullish_pin` / `bearish_pin` | Rejection wick longer than 2 × body, small opposite wick |
| `none` | Neither |

Rules:
- A pattern counts **only at a location** from section 1. A bullish engulfing in the
  middle of nowhere is not evidence.
- A sweep bar (`*_swept`) is itself a rejection: wick through, close back.
- `candle.volume_state` `spike` at a location is mild support. `unavailable` or `low` is
  neutral. Volume is tick volume; never call it institutional activity.
- Follow-through on the next bar cannot be seen; do not claim it.

## 4. Zone quality

| Feature | Raises quality | Lowers quality |
|---|---|---|
| Alignment | Zone side matches `structure_trend` and the higher-timeframe bias | Against either |
| Range position | Demand in `discount`, supply in `premium` | Demand in `premium`, supply in `discount` |
| Swing size | `structure_scope` is `external` | `internal` |
| Reaction | Pattern in the zone's direction, or a sweep close-back | Touch with no reaction; close in the lower third of the bar for a long |
| Room | Nearest opposing level ≥ 1.5 × stop distance away | Opposing level close by |
| State | `fresh` | `mitigated` (closed through) → the zone is gone |

## 5. Invalidation hierarchy

Use the first that applies to the location in play, and state which one you used:

```text
1. Far boundary of the order block     (bull_ob_bottom / bear_ob_top)
2. Far boundary of the FVG             (bull_fvg_bottom / bear_fvg_top)
3. Extreme of the sweep bar            (candle.low / candle.high)
4. Last swing                          (smc.swing_low / smc.swing_high)
```

A wick through a zone is not invalidation. A close through it is (`*_ob_freshness`
becomes `mitigated`, or `structure_event` prints against the idea).

## 6. Traps

Flag `possible_trap` when the payload shows any of:
- `bsl_taken` / `ssl_taken` on this bar together with an opposite `candle.pattern`.
- A close beyond `previous_day_high/low` or `session_high/low` on a `low` volume bar.
- `structure_event` BOS while both `mtf` ADX states are `ranging`.

Do not label a trap merely because price moved against an idea.

## 7. Status

| Situation | Status |
|---|---|
| No section-1 location on the idea's side | `WATCH` |
| Location, no reaction on this bar | `WAIT` |
| Location + reaction + trend regime + invalidation level | `REVIEW` |
| Location + reaction against the higher-timeframe bias | `COUNTERTREND_CANDIDATE` |
| Zone closed through | `INVALIDATED` |

## 8. Findings (only when this skill is used on its own)

```json
{
  "skill": "supply-demand-price-action-playbook",
  "status": "WATCH|WAIT|REVIEW|COUNTERTREND_CANDIDATE|INVALIDATED",
  "direction": "long|short|null",
  "regime": "bullish_trend|bearish_trend|range|transition|unknown",
  "location": "ob|fvg|sweep|day_level|none",
  "reaction": "pattern|sweep_close_back|none",
  "invalidation_level": null,
  "facts": ["string"],
  "conflicts": ["string"],
  "missing_data": ["string"]
}
```

## 9. Common mistakes

- Inventing a supply/demand zone the payload does not carry.
- Entering because price touched a zone, with no reaction.
- Using a candle pattern away from any location.
- Calling a wick through a zone a break.
- Calling a volume spike proof of anything on its own.
