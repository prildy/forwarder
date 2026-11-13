---
name: bbma
description: Read the bbma block of the XAUUSD TradingView payload with the BBMA method (Oma Ally) as a timing layer - Extreme, Reentry, CSM - for paper-only decision support. Never decides direction or location alone and never executes broker actions.
version: 0.3.0
metadata:
  hermes:
    tags: [trading, bbma, bollinger-bands, moving-average, xauusd, paper-trading]
    category: trading
---

# BBMA Timing Playbook v0.3.0

Paper analysis only; no broker execution; payload facts only. The shared safety rules,
the payload overview and the final output format are in
`trading-confluence-orchestrator` (sections 0, 2 and 9) and apply here.

**Role:** timing. BBMA says *when* an already-justified idea is mature. Direction comes
from the higher-timeframe bias, location and invalidation from ICT/SMC and price action.

## 1. The method in brief

```text
Extreme → MHV → CSAK → Reentry → CSM
```

| Signal | Textbook meaning | Use |
|---|---|---|
| Extreme | MA5/MA10 pushed outside the Bollinger Band | Early warning of exhaustion. Never an entry |
| MHV | After an Extreme, price fails to close outside the band again | Old momentum fading |
| CSAK | Strong directional candle closing beyond MA5/10 and the mid band | New direction confirmed |
| Reentry | Pullback to MA5/10 or mid band that holds | The entry-review stage |
| CSM | Candle closes outside the band in trend direction | Momentum; review targets, do not chase |

## 2. What the `bbma` block really contains

All values are on the chart timeframe and describe the current closed bar.

| Field | Exact definition in the Pine script | Reliability |
|---|---|---|
| `bb_top`, `bb_mid`, `bb_low`, `bb_params` | Bollinger 20 / 2.0 (as stated in `bb_params`) | Use |
| `ma5_high`, `ma10_high`, `ma5_low`, `ma10_low` | Weighted MA of highs / lows | Use |
| `ema50`, `ma50`, `ma200` | EMA 50, SMA 50, SMA 200 | Context and possible targets |
| `trend`, `cycle_direction` | `up`: close > EMA50 and mid band rising; `down`: mirror; else `sideways` / `unknown` | Use as BBMA trend |
| `price_position` | `above_upper`, `upper_half`, `lower_half`, `below_lower` | Use |
| `extreme_sell` / `extreme_buy`, `extreme_state` | MA5-high or MA10-high above `bb_top` (`top`); MA5-low or MA10-low below `bb_low` (`bottom`) | Use; true only while it lasts |
| `csm_buy` / `csm_sell`, `csm_state` | Close crossed outside the band on this bar | Use; bar-only |
| `reentry_buy` | Trend `up`, low ≤ max(MA5-low, MA10-low), close > min(MA5-low, MA10-low), close > mid band | Use; bar-only |
| `reentry_sell` | Mirror of `reentry_buy` | Use; bar-only |
| `reentry_state` | Count of reentry events since the last new Extreme: `none`, `first`, `second`, `continuation` | Use, but it does not say which direction; take direction from `reentry_buy/sell` and `trend` |
| `bars_since_extreme`, `bars_since_reentry`, `bars_since_csm` | Bars since the event last started | Use |
| `mhv_state`, `bars_since_mhv` | `valid` whenever the bar's range spans the mid band | **Not a real MHV. Ignore.** |
| `csak_state` | Small-body candle spanning the mid band | **Not a real CSAK. Ignore.** |

There is no `bars_since_csak`, no cycle history and no higher-timeframe BBMA state.

## 3. Deriving what the payload does not label

- **CSAK on this bar (derived).** Bullish: `candle.close > candle.open`, close above
  `bb_mid`, `ma5_high` and `ma10_high`. Bearish: close below open, `bb_mid`, `ma5_low` and
  `ma10_low`. Report it as `csak_like_bar`; you cannot know whether it is the first one.
- **MHV cannot be confirmed.** If a reversal idea depends on it, add `bbma_mhv` to
  `missing_data`. A liquidity sweep on the Extreme side (`bsl_swept` after a top Extreme,
  `ssl_swept` after a bottom Extreme) is acceptable evidence that the old move failed.
- **A full cycle cannot be proven from one bar.** Do not claim one.

## 4. Timing rules

For direction `D` given by the orchestrator:

| Observation on this bar | Timing verdict |
|---|---|
| `reentry_<D>` true and `reentry_state` is `second` or `continuation` | **Mature** timing |
| `reentry_<D>` true and `reentry_state` is `first` | **Early** timing; acceptable only with a strong location |
| `csak_like_bar` in `D`, no reentry | Direction confirmation only; wait for the pullback |
| `csm_state` equals `D` | Take-profit review. Never propose a new entry on this bar |
| Extreme on the side `D` trades into (`top` for a long) | Exhaustion warning; downgrade |
| Extreme on the opposite side with `bars_since_extreme` ≤ 10 | Supports a reversal idea in `D` (countertrend protocol only) |
| `trend` is `sideways` | No BBMA timing; neutral |
| `trend` opposite to `D` | Conflict |

Reentry quality bonus (optional): MA5/10 and the mid band are close,
`abs(ma5_low − bb_mid) ≤ 0.3 × candle.atr` for longs (use `ma5_high` for shorts).

MA50 / MA200: context and possible reaction areas only. Never a reason to enter, never an
automatic veto.

## 5. Findings (only when this skill is used on its own)

```json
{
  "skill": "bbma",
  "verdict": "MATURE|EARLY|CONFIRMATION_ONLY|TAKE_PROFIT_REVIEW|NEUTRAL|CONFLICT",
  "direction": "long|short|null",
  "facts": ["string"],
  "conflicts": ["string"],
  "missing_data": ["string"]
}
```

## 6. Common mistakes

- Entering because an Extreme, a CSAK-like bar or a CSM appeared.
- Trusting `mhv_state` or `csak_state` from the payload.
- Assuming the direction of `reentry_state`, or assuming a full cycle from one bar.
- Using the chart-timeframe BBMA trend as the market bias.
- Proposing an entry right after a CSM.
