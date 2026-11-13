---
name: ichimoku-filter-playbook
description: Use the ichimoku block and mtf cloud biases of the XAUUSD TradingView payload as a regime and momentum filter for a direction proposed by other skills. Not a standalone strategy; cannot create an entry and never executes broker actions.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, ichimoku, kumo, trend-filter, xauusd, paper-trading]
    category: trading
---

# Ichimoku Filter Playbook v0.2.0

Paper analysis only; no broker execution; payload facts only. The shared safety rules,
the payload overview and the final output format are in
`trading-confluence-orchestrator` (sections 0, 2 and 9) and apply here.

**Role:** filter. Given a direction `D` from other skills, answer `SUPPORT`, `NEUTRAL` or
`CONFLICT`. Ichimoku never creates a direction, an entry, a stop or a target here.

## 1. What the `ichimoku` block really contains

Computed on the chart timeframe with the parameters in `parameter_profile`
(for example `9-26-52`).

| Field | Exact definition | Caveat |
|---|---|---|
| `tenkan`, `kijun` | Donchian midpoints | |
| `span_a`, `span_b`, `cloud_top`, `cloud_bottom` | The cloud **at the current bar** (spans shifted forward 25 bars) | |
| `price_vs_kumo` | `above` / `below` / `inside` / `unknown` by the close | Never `touching_*` |
| `kumo_direction` | `bullish` when today's un-shifted Span A > Span B | This is the **future** cloud, not the one at price |
| `kumo_thickness_atr`, `kumo_thickness_state` | Cloud height ÷ ATR; `thin` < 0.5, `medium` < 1.5, else `thick` | Use the state as given |
| `tenkan_vs_kijun` | `bullish_cross` / `bearish_cross` on the cross bar, otherwise `bullish_aligned` / `bearish_aligned` / `neutral` | |
| `tk_cross`, `tk_cross_location` | Cross on this bar; location says whether **both lines** are `above_kumo`, `below_kumo` or `inside_kumo` | Location is always filled, cross or not |
| `tenkan_slope`, `kijun_slope` | `up` / `down` / `flat` versus the prior bar | One-bar slope; noisy |
| `chikou`, `chikou_confirmation` | Close versus the bar 25 bars ago: above its high → `bullish_clear`, below its low → `bearish_clear`, else `neutral` | Never `blocked`; cloud is not checked |
| `kumo_breakout_state` | `bullish_confirmed` / `bearish_confirmed` only on the bar whose close crosses out of the cloud | No false-breakout detection |

Higher timeframes: `mtf.m1/m5/m15.cloud_bias` (`bullish` = close above that timeframe's
cloud, `bearish` = below, `neutral` = inside or unknown). Nothing else from Ichimoku is
available above the chart timeframe.

## 2. Filter rules for direction `D`

Count the chart-timeframe facts that agree with `D` (long shown; mirror for short):

1. `price_vs_kumo` is `above`
2. `kumo_direction` is `bullish`
3. `tenkan_vs_kijun` is `bullish_cross` or `bullish_aligned`
4. `chikou_confirmation` is `bullish_clear`

| Condition | Verdict |
|---|---|
| Fact 1 true and at least two of facts 2–4 true, and `mtf.m5.cloud_bias` is not opposite | `SUPPORT` |
| `price_vs_kumo` is on the opposite side and at least two of facts 2–4 are opposite | `CONFLICT` |
| `mtf.m5.cloud_bias` and `mtf.m15.cloud_bias` are both opposite to `D` | `CONFLICT` |
| `price_vs_kumo` is `inside` | `NEUTRAL`, with note `inside_kumo` (transition; weaker trend-following) |
| Anything else | `NEUTRAL` |
| `ichimoku` block missing or `price_vs_kumo` `unknown` | `MISSING_DATA` (treated as `NEUTRAL` by the orchestrator) |

Modifiers to report (they do not change the verdict by themselves):
- `kumo_thickness_state` `thin`: breakouts through it are less meaningful.
- `tk_cross` on this bar with `tk_cross_location` `inside_kumo`: weak cross.
- `tk_cross` in `D` with location on the wrong side of the cloud: early / aggressive.
- `kumo_breakout_state` in `D` on this bar: regime may be changing in favour.
- `tenkan_slope` and `kijun_slope` both `flat`: low momentum.

## 3. Limits

- The chart-timeframe Ichimoku is execution context; it does not set the market bias.
  The orchestrator takes bias from `mtf`.
- Kijun and the cloud are context levels. Structural invalidation from the order block,
  FVG or swing always has priority.
- Do not compare readings taken with different `parameter_profile` values.

## 4. Findings (only when this skill is used on its own)

```json
{
  "skill": "ichimoku-filter-playbook",
  "verdict": "SUPPORT|NEUTRAL|CONFLICT|MISSING_DATA",
  "direction_tested": "long|short|null",
  "facts": ["string"],
  "notes": ["string"],
  "missing_data": ["string"]
}
```

## 5. Common mistakes

- Trading a Tenkan–Kijun cross or a cloud position by itself.
- Reading `kumo_direction` as the cloud price is in.
- Expecting `chikou_confirmation` to report `blocked`.
- Calling a breakout confirmed beyond the single bar the payload reports.
- Letting Kijun override the structural stop.
