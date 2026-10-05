---
name: momentum-filter-stochrsi-adx-di
description: Filter trend strength and timing momentum using ADX, DI+/DI−, and Stochastic RSI after location, liquidity reaction, and market structure are already validated. This is not a standalone strategy and never executes broker actions.
version: 0.1.0
metadata:
  hermes:
    tags: [trading, momentum, stochastic-rsi, adx, di, trend-strength, xauusd, paper-trading]
    category: trading
---

# Momentum Filter: Stochastic RSI + ADX/DI v0.1.0

## 0. Purpose, Scope, and Safety Rules

This skill is a **momentum and trend-strength filter**. It must be used only after another layer has identified a valid location and structure.

```text
REQUIRED ORDER:
Data Quality
→ Market Regime
→ Trade Location
→ Liquidity Reaction
→ Market Structure
→ Momentum Filter (this skill)
→ BBMA/Ichimoku timing and confluence
→ Risk Gate
→ Human Review
```

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

This skill answers:

```text
1. Is market energy trending, developing, weak, or choppy?
2. Is DI directional pressure bullish, bearish, neutral, or unstable?
3. Is Stochastic RSI timing momentum aligned with an already-valid structure?
4. Does momentum support, downgrade, or conflict with a reversal/continuation scenario?
```

This skill must never:

- Create an entry from ADX, DI, Stoch RSI, overbought, oversold, or crossover alone.
- Buy merely because Stoch RSI is oversold.
- Sell merely because Stoch RSI is overbought.
- Treat ADX as a directional indicator; ADX measures strength, while DI relationship provides directional context.
- Use 30S or 15S ADX/DI as independent market bias.
- Override Data Quality Gate, Supply-Demand/Price Action, ICT/SMC, BBMA, Ichimoku, Risk Engine, or human review.
- Invent indicator values, crosses, slopes, or divergence from a screenshot.
- Alter thresholds, Pine Script parameters, or strategy rules automatically based on a small sample.

All facts must come from validated structured payload/rule-engine fields. Screenshots are only optional non-numeric context.

## 1. Role in the Multi-Skill System

| Framework | Primary role |
|---|---|
| Supply-Demand & Price Action | Trade location, zone reaction, candle confirmation, BOS/CHoCH, invalidation |
| ICT/SMC | Liquidity, sweep/reclaim/acceptance, MSS, FVG, OB, internal/external structure |
| BBMA | Timing cycle and reentry maturity |
| Ichimoku | Regime, trend/momentum, Kumo/Kijun filter |
| **Momentum Filter** | Trend strength via ADX/DI and final timing momentum via Stoch RSI |
| Rule/Risk Engine | Data quality, cooldown, risk, R:R, no-trade/halt |
| Confluence Orchestrator | Resolves support/conflict and produces final decision-support status |

This skill may support, downgrade, warn, or remain neutral. It does not issue broker commands.

## 2. Source Hierarchy and Missing-Data Rules

Use information in this order:

1. Validated `momentum_filter`, `adx_di`, and `stoch_rsi` payload blocks.
2. Multi-timeframe payload snapshots.
3. Structured location/structure results from Supply-Demand, ICT/SMC, and BBMA skills.
4. Screenshot only as non-numeric supplementary context.

If required values are not supplied, list them in `missing_data`.

```text
No ADX value or state → do not call market strong/weak.
No DI+/DI− → do not claim buyer/seller dominance.
No confirmed bar → do not confirm cross.
No K/D values/cross state → do not claim Stoch timing.
No valid location/structure context → momentum result must be NEUTRAL or CONTEXT_MISSING.
```

## 3. Status Vocabulary

Use the following filter statuses only:

| Status | Meaning |
|---|---|
| `SUPPORTS_BUY` | Momentum supports an already-valid bullish location/structure scenario |
| `SUPPORTS_SELL` | Momentum supports an already-valid bearish location/structure scenario |
| `NEUTRAL` | Momentum does not materially improve or weaken the scenario |
| `CONFLICT` | Momentum materially opposes the proposed scenario or internal readings conflict |
| `CHOPPY_WARNING` | Low/unstable ADX/DI conditions make trend-following unreliable |
| `CONTEXT_MISSING` | Location/structure has not been supplied, so momentum cannot be used correctly |
| `MISSING_DATA` | Required ADX/DI/Stoch data is unavailable or unconfirmed |

No status is a trade command.

## 4. Indicator Definitions and Parameter Discipline

### 4.1 Stochastic RSI

Default educational settings from the user's script:

```text
RSI Length: 14
Stochastic Length: 14
K smoothing: 3
D smoothing: 3
Upper zone: 80
Midpoint: 50
Lower zone: 20
```

Stochastic RSI is highly sensitive. It is useful for timing momentum after structure is validated, but can create frequent false signals on very small timeframes.

### 4.2 ADX and DI

Default educational settings from the user's script:

```text
Length: 14
Initial ADX threshold: 20
```

- ADX measures **trend strength**, not trend direction.
- `+DI > −DI` indicates relative bullish directional pressure.
- `−DI > +DI` indicates relative bearish directional pressure.

### 4.3 Parameter rule

The payload must include its parameter profile. Do not compare outputs from different parameter sets as if they were equivalent.

```json
{
  "adx_di": { "length": 14, "threshold": 20 },
  "stoch_rsi": { "rsi_length": 14, "stoch_length": 14, "smooth_k": 3, "smooth_d": 3 }
}
```

Any parameter change requires a distinct version label and separate backtest/journal evaluation.

## 5. ADX/DI Trend-Strength Filter

### 5.1 DI directional context

| Condition | Interpretation | Filter use |
|---|---|---|
| `+DI > −DI` | Buyer pressure relatively stronger | Supports bullish continuation/pullback if location and structure are bullish |
| `−DI > +DI` | Seller pressure relatively stronger | Supports bearish continuation/pullback if location and structure are bearish |
| DI close / repeatedly crossing | Direction unstable | Choppy/neutral warning; wait for structure clarity |
| DI unavailable | Direction unknown | Do not infer bias |

### 5.2 ADX strength states

Initial ranges are reference labels only. They must be backtested per instrument/timeframe.

| ADX state | Initial guide | Meaning | Filter action |
|---|---:|---|---|
| `weak` | ADX < 20 | Low trend energy / possible choppy market | Downgrade trend-following; do not force continuation |
| `developing` | ADX 20–25 | Trend may be forming | Require stronger location and structure confirmation |
| `strong` | ADX > 25 and rising/stable | Meaningful trend energy | Supports continuation if DI and structure align |
| `weakening` | ADX high but falling | Momentum may be fading | Not reversal by itself; inspect structure, DI, and acceptance/reclaim |
| `unknown` | Missing data | Cannot evaluate strength | List missing data |

### 5.3 Timeframe rule for ADX/DI

- ADX/DI is most useful on M5, M15, H1, and H4 for this system.
- M3/M1 may be used only as supporting context after M5/M15 direction is available.
- 30S/15S ADX/DI must never create an independent directional bias.
- If only 30S ADX/DI is supplied, return `MISSING_DATA` or `CONTEXT_MISSING` for trend-strength assessment.

### 5.4 ADX/DI interpretation rules

```text
Bullish continuation support:
+DI > −DI
+ ADX developing/strong
+ bullish structure remains valid
+ acceptance/retest supports continuation

Bearish continuation support:
−DI > +DI
+ ADX developing/strong
+ bearish structure remains valid
+ acceptance/retest supports continuation

Choppy warning:
ADX weak OR DI repeatedly crosses
+ no clear structure/location

Possible weakening, not automatic reversal:
ADX falling after high reading
→ inspect reclaim/acceptance, sweep, MSS/CHoCH, and price action.
```

## 6. Stochastic RSI Timing Filter

### 6.1 Stoch RSI states

| State | Structured definition / use |
|---|---|
| `bullish_cross` | K crossed above D on confirmed bar |
| `bearish_cross` | K crossed below D on confirmed bar |
| `bullish_reset` | Oscillator pulled back during bullish context, then turns/crosses up with structure support |
| `bearish_reset` | Oscillator rebounded during bearish context, then turns/crosses down with structure support |
| `overbought` | K/D in or above upper zone; warning only, not sell signal |
| `oversold` | K/D in or below lower zone; warning only, not buy signal |
| `above_50` | Momentum on bullish half of oscillator range |
| `below_50` | Momentum on bearish half of oscillator range |
| `neutral` | No useful timing signal |
| `unknown` | Missing/unconfirmed data |

### 6.2 Non-negotiable Stoch rules

```text
Oversold ≠ automatic buy.
Overbought ≠ automatic sell.
K/D cross ≠ entry by itself.
```

Stoch RSI is only valid as final timing support after all of these exist:

1. Valid location from Supply-Demand/Price Action or ICT/SMC.
2. Valid reaction: reclaim or acceptance as applicable.
3. Valid structure: MSS/CHoCH for reversal, or HH-HL/LL-LH/BOS context for continuation.
4. Known structural invalidation reference.
5. No critical data-quality/risk failure.

### 6.3 Reversal timing

#### Bullish reversal timing

```text
Relevant demand / sell-side liquidity
→ sell-side sweep
→ reclaim + bullish displacement
→ bullish MSS/CHoCH
→ retest holds
→ Stoch RSI K crosses above D
→ momentum filter may SUPPORTS_BUY
```

#### Bearish reversal timing

```text
Relevant supply / buy-side liquidity
→ buy-side sweep
→ reclaim + bearish displacement
→ bearish MSS/CHoCH
→ retest fails
→ Stoch RSI K crosses below D
→ momentum filter may SUPPORTS_SELL
```

### 6.4 Continuation timing

#### Bullish continuation timing

```text
Bullish location/structure + acceptance above broken high
→ retest holds as support + higher low
→ ADX/DI supports bullish trend
→ Stoch RSI resets then K crosses above D,
   preferably recovering/holding above 50
→ SUPPORTS_BUY
```

#### Bearish continuation timing

```text
Bearish location/structure + acceptance below broken low
→ retest holds as resistance + lower high
→ ADX/DI supports bearish trend
→ Stoch RSI rebounds then K crosses below D,
   preferably returning/holding below 50
→ SUPPORTS_SELL
```

## 7. Sweep Reversal vs Continuation Matrix

A sweep is not automatically a reversal. Classify outcome with price behavior after the level break.

| Component | Sweep → Reversal | Break / Run → Continuation |
|---|---|---|
| Initial action | Important high/low breached then rejected | Important high/low breached with clear drive |
| Close | Reclaim: close returns inside prior range | Acceptance: close holds outside prior range |
| Time outside level | Short, unable to hold | Multiple rotations/candles hold outside |
| Retest | Break level fails; price returns inside | Old level flips to support/resistance |
| Micro structure | MSS/CHoCH opposite sweep direction | HH-HL or LL-LH remains in breakout direction; BOS supports |
| ADX/DI | Old DI pressure weakens/reverses; ADX may fade | Dominant DI holds; ADX develops/holds strong |
| Stoch RSI | Cross opposite sweep after structure is valid | Reset/pullback then cross returns with trend |
| Skill stance | Wait for reversal retest | Seek continuation retest; do not countertrend |

Key rule:

```text
Reclaim + displacement + MSS/CHoCH → reversal evidence.
Acceptance + successful retest + aligned structure → continuation evidence.
```

## 8. Multi-Timeframe Momentum Use

| Layer | Timeframes | Role |
|---|---|---|
| Macro/context | H4, H1, M15 | Major trend/market condition; optional depending payload |
| Trend-strength filter | M15, M5 | Primary ADX/DI reading for intraday/scalp context |
| Structure confirmation | M3, M1 | Sweep, reclaim/acceptance, displacement, MSS/CHoCH, retest |
| Timing only | M1, 30S, 15S | Stoch RSI and micro-candle trigger after context is established |

Rules:

- A Stoch cross on 30S without M1/M3/M5 location and structure is `CONTEXT_MISSING`.
- A strong M5 ADX cannot excuse entry at an invalid location.
- A countertrend setup must show stronger structure/sweep evidence; ADX/DI alone is not enough.
- If M5 ADX/DI and M1 timing conflict, report conflict rather than picking the preferred indicator.

## 9. Confluence and Conflict Rules

### 9.1 Core evidence required before momentum matters

1. Data quality passed.
2. A structured trade location exists.
3. Sweep/reclaim or acceptance/break behavior is classified.
4. Structure supports reversal or continuation.
5. Structural invalidation exists.

### 9.2 Momentum support

Momentum filter can add support when:

- DI direction aligns with scenario.
- ADX state supports the scenario type.
- Stoch timing aligns after a validated retest/structure event.
- No major conflict with Ichimoku/BBMA/ICT/Price Action.

### 9.3 Momentum conflict

Report `CONFLICT` when:

- Proposed buy but M5/M15 DI remains strongly bearish and no valid reversal structure exists.
- Proposed sell but M5/M15 DI remains strongly bullish and no valid reversal structure exists.
- ADX/DI is choppy while setup relies on trend continuation.
- Stoch cross opposes the scenario after structure has already been validated.
- Different relevant timeframes materially conflict.

### 9.4 Neutral result

`NEUTRAL` is valid when indicators are not clearly supportive or conflicting. Do not force a conclusion.

## 10. Required Payload Fields

Recommended combined payload block:

```json
{
  "momentum_filter": {
    "analysis_timeframe": "M5",
    "bar_confirmed": true,
    "adx_di": {
      "length": 14,
      "threshold": 20,
      "adx": null,
      "adx_prev": null,
      "adx_state": "weak|developing|strong|weakening|unknown",
      "di_plus": null,
      "di_minus": null,
      "di_bias": "bullish|bearish|neutral|unknown",
      "di_cross_state": "bullish_cross|bearish_cross|none|unknown"
    },
    "stoch_rsi": {
      "timeframe": "M1",
      "rsi_length": 14,
      "stoch_length": 14,
      "smooth_k": 3,
      "smooth_d": 3,
      "k": null,
      "d": null,
      "cross_state": "bullish_cross|bearish_cross|none|unknown",
      "zone": "below_20|between_20_50|between_50_80|above_80|unknown",
      "state": "bullish_reset|bearish_reset|overbought|oversold|neutral|unknown"
    }
  }
}
```

Rules:

- Use payload values from Pine Script/rule engine only.
- `bar_confirmed` must be true before cross states are treated as confirmed.
- Do not call a reset unless the rule engine provides it or the structured historical state makes it explicit.

## 11. Filter Evaluation Procedure

Evaluate in order:

1. Verify data quality and confirmed candle state.
2. Verify a valid location/structure context is supplied by upstream skills/rule engine.
3. Read ADX state on appropriate timeframe.
4. Read DI bias and stability.
5. Determine whether market is trending, developing, weak, or choppy.
6. Read Stoch RSI K/D cross, zone, and reset state on timing timeframe.
7. Compare momentum direction with proposed structure direction.
8. Return support, neutral, conflict, choppy warning, missing data, or context missing.

## 12. Output Contract

Return valid JSON only. Do not use Markdown code fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "skill": "momentum-filter-stochrsi-adx-di",
  "filter_status": "SUPPORTS_BUY|SUPPORTS_SELL|NEUTRAL|CONFLICT|CHOPPY_WARNING|CONTEXT_MISSING|MISSING_DATA",
  "context": {
    "proposed_direction": "buy|sell|null",
    "setup_type": "reversal|continuation|unknown",
    "location_valid": false,
    "structure_valid": false,
    "analysis_timeframe": "string|null",
    "timing_timeframe": "string|null"
  },
  "adx_di": {
    "adx": null,
    "adx_state": "weak|developing|strong|weakening|unknown",
    "di_plus": null,
    "di_minus": null,
    "di_bias": "bullish|bearish|neutral|unknown",
    "di_cross_state": "bullish_cross|bearish_cross|none|unknown",
    "effect": "supports|downgrades|neutral|unknown"
  },
  "stoch_rsi": {
    "k": null,
    "d": null,
    "cross_state": "bullish_cross|bearish_cross|none|unknown",
    "zone": "below_20|between_20_50|between_50_80|above_80|unknown",
    "state": "bullish_reset|bearish_reset|overbought|oversold|neutral|unknown",
    "effect": "supports|downgrades|neutral|unknown"
  },
  "confluence": {
    "supports": ["string"],
    "conflicts": ["string"],
    "neutral_notes": ["string"]
  },
  "missing_data": ["string"],
  "manual_review_checklist": ["string"],
  "journal_seed": {
    "adx_state": "string|null",
    "di_bias": "string|null",
    "stoch_state": "string|null",
    "filter_effect": "supports|downgrades|neutral|unknown",
    "technical_lesson_candidate": "string|null"
  }
}
```

## 13. Paper Journal and Learning Rules

For every momentum-filter analysis, store when available:

- Event ID, symbol, session, and timeframe stack.
- Analysis timeframe and timing timeframe.
- ADX, prior ADX/slope state, DI+/DI−, DI bias, and DI stability.
- Stoch K/D values, cross state, zone, and reset state.
- Setup type: reversal or continuation.
- Upstream location/structure state.
- Momentum filter result: supports, neutral, downgrades, conflict, or choppy warning.
- Final orchestrator status and outcome.
- Technical lesson and rule-change candidate.

Questions to answer after sufficient sample size:

```text
- Do continuation setups work better when ADX is strong and DI aligns?
- Does ADX < 20 meaningfully increase false continuation signals?
- Does Stoch RSI reset + recross improve timing after valid retests?
- Does Stoch RSI above 80/below 20 add useful information, or create premature countertrend signals?
- On which timeframe does ADX/DI add value for XAUUSD M1/M3/M5 execution?
```

The agent may propose a hypothesis after a meaningful sample; it may not change thresholds or rules automatically.

## 14. Common Mistakes to Avoid

- Buy because Stoch RSI is oversold.
- Sell because Stoch RSI is overbought.
- Treat ADX as direction instead of strength.
- Use DI crosses on 30S as market bias.
- Use ADX > 25 to ignore a broken supply/demand zone or invalid structure.
- Call ADX weakening a reversal without reclaim/MSS/CHoCH.
- Let a Stoch cross override missing location, missing invalidation, or risk failure.
- Count ADX, DI, and Stoch as three independent core confirmations; they are all momentum-related and must be weighted as one filter layer.
- Change thresholds after a few trades without backtesting and journal review.
