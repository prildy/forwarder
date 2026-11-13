---
name: momentum-filter-stochrsi-adx-di
description: Filter trend strength and timing momentum from the adx_di, stoch_rsi, macd, vw_trend and mtf blocks of the XAUUSD TradingView payload, after location and structure are already validated. Not a standalone strategy and never executes broker actions.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, momentum, stochastic-rsi, adx, di, macd, xauusd, paper-trading]
    category: trading
---

# Momentum Filter v0.2.0 — ADX/DI, Stoch RSI, MACD, VW trend

Paper analysis only; no broker execution; payload facts only. The shared safety rules,
the payload overview and the final output format are in
`trading-confluence-orchestrator` (sections 0, 2 and 9) and apply here.

**Role:** filter. Given a direction `D` that already has a location and structure, answer
`SUPPORT`, `NEUTRAL` or `CONFLICT`, and flag `choppy`. All four indicator families here
measure momentum; together they count as **one** layer, not four confirmations.

```text
Oversold is not a buy. Overbought is not a sell. A cross is not an entry.
ADX measures strength, not direction. Direction comes from DI.
```

## 1. Where the data is

The blocks are **top-level**. `momentum_filter` holds only `analysis_timeframe` and
`bar_confirmed`; it does not nest the indicators.

### `adx_di` (chart timeframe)

| Field | Exact definition |
|---|---|
| `length`, `threshold` | Parameters (default 14, 20) |
| `adx`, `adx_prev`, `adx_slope` | Value, prior value, `rising` / `falling` |
| `di_plus`, `di_minus`, `di_bias` | `bullish` when +DI > −DI |
| `adx_state` | Below threshold: `developing` if rising, else `weak`. At or above: `strong` if rising, else `weakening` |
| `di_cross_state` | `bullish_cross` / `bearish_cross` on the cross bar, else `none` |

### `mtf.m1`, `mtf.m5`, `mtf.m15`

`adx`, `adx_state` (`trending` when ADX ≥ 20, else `ranging`; a different vocabulary from
the chart block) and `di_bias`. **Use m5 and m15 for trend strength.** The chart-timeframe
ADX/DI is timing context only and never sets bias.

### `stoch_rsi` (chart timeframe)

| Field | Exact definition |
|---|---|
| `k`, `d`, parameters | Values and settings (14, 14, 3, 3) |
| `cross` | `bullish` when K crossed above D on this bar, `bearish` the reverse, `none` |
| `zone` | `overbought` (K > 80), `oversold` (K < 20), `neutral` |
| `zone_band` | `above_80`, `between_50_80`, `between_20_50`, `below_20` |
| `state` | `bullish_reset`: bullish cross while K or D is below 20. `bearish_reset`: bearish cross while K or D is above 80. Otherwise `overbought` / `oversold` / `neutral` |

There is no `cross_state` field; use `cross`.

### `macd` (chart timeframe)

`macd`, `signal`, `histogram`, `cross` (`bullish|bearish|none`, this bar),
`divergence_now` (this bar; confirmed 5 bars after the pivot), `divergence_last` and
`divergence_bars_ago` (persistent). Values: `regular_bullish`, `hidden_bullish`,
`regular_bearish`, `hidden_bearish`, `none`. Regular divergence hints at exhaustion;
hidden divergence at continuation.

### `vw_trend` (chart timeframe)

`trend` flips to `bullish` on a close above VWMA(20) + 1 ATR, to `bearish` on a close
below VWMA − 1 ATR, and holds in between (`undefined` before the first flip). `flipped`
is true on the flip bar; `bars_in_trend` counts bars since. Volume is tick volume, and the
basis falls back to a simple average when volume is missing.

## 2. Filter rules for direction `D`

**Step 1 — trend strength (higher timeframes).**
- `choppy`: `mtf.m5.adx_state` and `mtf.m15.adx_state` are both `ranging`.
- `hta_with`: `mtf.m5.di_bias` equals `D` and `mtf.m15.di_bias` is not opposite.
- `hta_against`: `mtf.m5.di_bias` and `mtf.m15.di_bias` are both opposite to `D`.

**Step 2 — timing (chart timeframe).** Count agreement with `D`:
- `stoch_rsi.cross` in `D`, or `state` is the `D` reset.
- `macd.cross` in `D`, or `histogram` on the `D` side of zero.
- `vw_trend.trend` equals `D`.
- `adx_di.di_bias` equals `D` with `adx_state` `developing` or `strong`.

**Step 3 — verdict.**

| Condition | Verdict |
|---|---|
| `hta_against` | `CONFLICT` |
| `stoch_rsi.cross` against `D` on this bar | `CONFLICT` |
| `hta_with` and at least two timing items agree | `SUPPORT` |
| `choppy` and the setup is a continuation | `NEUTRAL` with flag `choppy` (cannot be `SUPPORT`) |
| Anything else | `NEUTRAL` |
| `adx_di`, `stoch_rsi` or `mtf` missing | `MISSING_DATA` (treated as `NEUTRAL`) |

Notes to report (no effect on the verdict by themselves):
- Stoch `zone` extended in the direction of `D` (`overbought` for a long): late entry risk.
- `adx_state` `weakening`: momentum fading; not a reversal by itself.
- `macd.divergence_last` regular **against** `D` within 30 bars: exhaustion warning.
- `macd.divergence_last` regular **in** `D` within 30 bars: supports a countertrend idea
  (orchestrator section 7).
- `vw_trend.flipped` against `D` on this bar: fresh opposing pressure.

## 3. Limits

- Without a validated location and structure from the other skills the verdict is
  `NEUTRAL`: momentum cannot rescue a missing location, stop or risk gate.
- Thresholds (ADX 20, Stoch 80/20) are the script's settings, not tuned values. Do not
  change them; do not compare readings taken with different parameters.

## 4. Findings (only when this skill is used on its own)

```json
{
  "skill": "momentum-filter-stochrsi-adx-di",
  "verdict": "SUPPORT|NEUTRAL|CONFLICT|MISSING_DATA",
  "direction_tested": "long|short|null",
  "flags": ["choppy"],
  "facts": ["string"],
  "notes": ["string"],
  "missing_data": ["string"]
}
```

## 5. Common mistakes

- Buying oversold or selling overbought.
- Taking bias from the chart-timeframe DI or a chart-timeframe DI cross.
- Counting ADX, DI, Stoch, MACD and VW trend as separate confirmations.
- Calling `weakening` ADX a reversal.
- Looking for the indicators inside `momentum_filter`.
