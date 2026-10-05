---
name: ichimoku-filter-playbook
description: Evaluate Ichimoku Cloud as a structured trend, regime, momentum, and dynamic support-resistance filter. This skill is not a standalone trading strategy and cannot create an entry by itself.
version: 0.1.0
metadata:
  hermes:
    tags: [trading, ichimoku, kumo, tenkan, kijun, chikou, trend-filter, xauusd, paper-trading]
    category: trading
---

# Ichimoku Cloud Filter Playbook v0.1.0

## 0. Purpose, Scope, and Safety Rules

This skill uses Ichimoku Cloud only as a **filter layer** inside the multi-skill trading system.

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

Its purpose is to answer:

```text
1. Is market regime bullish, bearish, neutral, transition, or unclear?
2. Does Ichimoku support, oppose, or remain neutral toward a setup
   proposed by Supply-Demand/Price Action, ICT/SMC, or BBMA?
3. Is price inside Kumo, near a Kumo boundary, or clearly outside it?
4. Does Tenkan–Kijun momentum and Chikou confirmation support the idea?
5. Should the filter support, downgrade, or block an entry review?
```

This skill is **not** allowed to create an entry, SL, TP, broker action, or directional trade command on its own. It only provides a regime/confluence assessment to the Confluence Orchestrator.

The agent must never:

- Treat a Tenkan–Kijun cross alone as an entry signal.
- Treat price above/below Kumo alone as a trade command.
- Invent cloud values, cloud thickness, crosses, Chikou position, or historical price relation.
- Read precise Ichimoku values from a screenshot as factual data.
- Override Data Quality Gate, Rule Engine, Supply-Demand/Price Action invalidation, BBMA timing, or risk rules.
- Change Ichimoku parameters automatically from a few wins/losses.

All Ichimoku facts must come from validated structured payload fields or a deterministic rule engine. Screenshots are only non-numeric supplemental context.

## 1. Role in the Multi-Skill System

| Framework | Primary role |
|---|---|
| Supply-Demand & Price Action | Trade location, zone quality, candle reaction, BOS/CHoCH, structural invalidation |
| ICT/SMC | Liquidity, sweep, FVG, OB, internal/external structure, session context |
| BBMA | Timing cycle: Extreme, MHV, CSAK, Reentry, CSM |
| **Ichimoku** | Trend/regime, dynamic Kumo support/resistance, momentum filter, no-trade/transition warning |
| Rule/Risk Engine | Data validity, cooldown, R:R, risk limits, no-trade/halt |
| Confluence Orchestrator | Combines all support/conflict and returns final decision-support status |

This skill may return `SUPPORT`, `NEUTRAL`, `CONFLICT`, `NO_TRADE_ZONE`, or `MISSING_DATA`. It does not return buy/sell commands.

## 2. Ichimoku Components

Use the parameter set sent by the payload. Do not assume parameters are 9-26-52 unless payload explicitly provides them.

| Component | Function in this skill |
|---|---|
| Tenkan-sen | Short-term momentum/reference line |
| Kijun-sen | Medium-term equilibrium, dynamic support/resistance, trend stability reference |
| Senkou Span A | One Kumo boundary / forward projection component |
| Senkou Span B | One Kumo boundary / forward projection component |
| Kumo | Dynamic support/resistance and regime zone |
| Chikou Span | Trend/momentum confirmation when structured data is available |

Default parameter profiles may be recorded, but must not be mixed:

| Profile | Typical use | Note |
|---|---|---|
| `9-26-52` | Standard / H4-D1 / swing context | Default Ichimoku profile |
| `5-13-26` | Intraday/scalping experiment | More responsive but noisier; use only after separate backtest |
| `unknown` | Parameter not provided | Agent must not assume profile |

## 3. Source Hierarchy and Missing-Data Rules

Use facts in this order:

1. Validated `ichimoku` payload block.
2. Multi-timeframe snapshots that contain Ichimoku state.
3. Structured price-action/zone/BBMA/ICT context from other layers.
4. Screenshot only as non-numeric supporting context.

If fields are missing, state so explicitly. Examples:

```text
No price_vs_kumo → do not label market above/below/inside Kumo.
No tenkan_vs_kijun → do not claim bullish/bearish cross.
No chikou state → do not claim Chikou confirmation.
No kumo thickness or ATR normalization → do not call Kumo thick/thin.
No confirmed bar → do not confirm Kumo breakout or TK cross.
```

## 4. Objective Ichimoku Vocabulary

### 4.1 Price position relative to Kumo

| Value | Meaning at this filter layer |
|---|---|
| `above` | Bullish regime support; Kumo may act as dynamic support below price |
| `below` | Bearish regime support; Kumo may act as dynamic resistance above price |
| `inside` | Transition/consolidation/noise warning; default downgrade or no-trade filter |
| `touching_top` | Price testing upper Kumo boundary; needs price-action confirmation |
| `touching_bottom` | Price testing lower Kumo boundary; needs price-action confirmation |
| `unknown` | Insufficient payload data |

### 4.2 Kumo direction

| Value | Interpretation |
|---|---|
| `bullish` | Span A above Span B; forward cloud supports bullish context |
| `bearish` | Span B above Span A; forward cloud supports bearish context |
| `neutral` | No clear directional cloud context |
| `unknown` | Missing data |

### 4.3 Kumo thickness

Thickness must be normalized if possible, preferably by ATR.

```text
kumo_thickness_atr = abs(span_a - span_b) / ATR
```

The thresholds below are only initial labels and must later be backtested per instrument/timeframe:

| State | Initial guide | Meaning |
|---|---|---|
| `thin` | thickness < 0.30 ATR | Easier to penetrate; greater false-break/transition risk |
| `medium` | 0.30–0.80 ATR | Normal dynamic support/resistance |
| `thick` | > 0.80 ATR | Stronger potential support/resistance; not a guarantee |
| `unknown` | No ATR/spans | No thickness claim allowed |

### 4.4 Tenkan–Kijun relationship

| Value | Meaning |
|---|---|
| `bullish_cross` | Tenkan crossed above Kijun on confirmed bar, if rule engine provides event |
| `bearish_cross` | Tenkan crossed below Kijun on confirmed bar, if rule engine provides event |
| `bullish_aligned` | Tenkan above Kijun without a newly detected cross |
| `bearish_aligned` | Tenkan below Kijun without a newly detected cross |
| `neutral` | Lines overlapping/flat/unclear |
| `unknown` | Missing data |

Cross quality depends on its location relative to Kumo:

| Cross / alignment location | Filter quality |
|---|---|
| Bullish TK above Kumo | Strong bullish support, not entry alone |
| Bearish TK below Kumo | Strong bearish support, not entry alone |
| Any TK cross inside Kumo | Weak/neutral; default downgrade |
| Bullish TK below Kumo | Early/aggressive only; needs strong non-Ichimoku evidence |
| Bearish TK above Kumo | Early/aggressive only; needs strong non-Ichimoku evidence |

### 4.5 Chikou confirmation

| Value | Meaning |
|---|---|
| `bullish_clear` | Chikou confirmed above historical price/cloud according to rule engine |
| `bearish_clear` | Chikou confirmed below historical price/cloud according to rule engine |
| `blocked` | Chikou intersects/overlaps historical price or cloud; trend confirmation weak |
| `neutral` | No directional confirmation |
| `unknown` | Missing data |

Chikou is a confirmation filter. It cannot create a setup by itself.

## 5. Regime Filter Rules

### 5.1 Strong bullish filter support

Classify as `BULLISH_SUPPORT` when most available facts align:

- Price is above Kumo.
- Kumo direction is bullish.
- Tenkan–Kijun is bullish aligned or bullish cross.
- Chikou is bullish clear.
- Price action / Supply-Demand / BBMA/ICT direction is also bullish or not contradictory.

### 5.2 Strong bearish filter support

Classify as `BEARISH_SUPPORT` when most available facts align:

- Price is below Kumo.
- Kumo direction is bearish.
- Tenkan–Kijun is bearish aligned or bearish cross.
- Chikou is bearish clear.
- Price action / Supply-Demand / BBMA/ICT direction is also bearish or not contradictory.

### 5.3 Inside-Kumo no-trade / downgrade rule

Price inside Kumo is a default `NO_TRADE_ZONE` or `FILTER_CONFLICT` for trend-following entries.

Exceptions are not automatic. If another skill identifies a high-quality reversal or breakout structure, Ichimoku should return:

```text
NEUTRAL_TO_CAUTION
```

and list the required confirmation:

- Confirmed close outside Kumo.
- Price action/structure confirmation.
- BBMA timing confirmation if BBMA is used.
- Optional volume confirmation when reliable data exists.

Ichimoku must not block all trades forever inside cloud; it must state that confidence is reduced and the system needs stronger non-Ichimoku evidence.

### 5.4 Kumo breakout rule

A Kumo breakout is only a filter event, not an entry.

For a bullish breakout support:

1. Confirmed candle close above Kumo.
2. No immediate close back inside Kumo, if follow-through data is available.
3. Tenkan–Kijun not materially bearish.
4. Prefer Chikou bullish/clear when available.
5. Supply-Demand/Price Action or ICT/SMC must provide location/structure evidence.

Mirror the rule for bearish breakout.

If price breaks Kumo but closes back inside quickly, flag `POSSIBLE_FALSE_BREAKOUT` and downgrade to `WAIT`/`WATCH`.

### 5.5 Kumo boundary reaction

Kumo is a dynamic area, not a single exact price.

- In bullish context, pullback/reaction at top/bottom Kumo may support a demand/retest narrative only if Price Action/Supply-Demand confirms it.
- In bearish context, reaction at Kumo may support a supply/retest narrative only if structure confirms it.
- A thick Kumo may be meaningful support/resistance, but never guarantees bounce.
- A thin Kumo signals potential easy penetration/transition and requires stronger confirmation.

## 6. Momentum Filter Rules

### 6.1 Tenkan and Kijun slope

If the payload provides deterministic slope states:

| Tenkan slope | Kijun slope | Filter meaning |
|---|---|---|
| Up | Up | Bullish momentum support |
| Down | Down | Bearish momentum support |
| Flat | Flat | Range/low-momentum warning |
| Opposing | Opposing | Transition/conflict warning |
| Unknown | Any | Do not infer slope |

### 6.2 Kijun as equilibrium reference

Kijun may be used as dynamic equilibrium/retest context, but it is not a mandatory SL/TP rule in this system.

- Price holding above a rising Kijun can support bullish context.
- Price holding below a falling Kijun can support bearish context.
- A confirmed close across Kijun may be a warning, but cannot invalidate a trade independently of structural OB/FVG/swing rules.
- Structural invalidation from Supply-Demand/Price Action and Rule Engine has priority over Kijun.

### 6.3 Momentum conflict examples

Flag conflict if:

- Proposed buy but price remains below bearish Kumo with bearish TK and bearish Chikou.
- Proposed sell but price remains above bullish Kumo with bullish TK and bullish Chikou.
- Price is inside Kumo and TK repeatedly crosses/flat.
- Kumo is thin while price action is attempting breakout without structural confirmation.

## 7. Multi-Timeframe Ichimoku Use

### 7.1 Roles

| Layer | Typical TF | Ichimoku role |
|---|---|---|
| Macro context | W1, D1, H4, H1, M30 | Regime, major Kumo, broad trend/transition |
| Main analysis | M15, M5, M3, M1 | Trend filter and momentum alignment with setup location |
| Execution | M3, M1, 30S | Fine confirmation only; no independent bias from 30S |

### 7.2 Rules

- Higher timeframe Ichimoku is context, not an absolute veto.
- A lower-timeframe countertrend setup can exist, but must be `COUNTERTREND_REVIEW` and supported strongly by Price Action/Supply-Demand and ICT/SMC.
- 30S Ichimoku cannot create independent trend bias. It may only provide execution timing after M1/M3/M5 context is present.
- If multiple timeframes conflict, report the conflict rather than averaging them into a false conclusion.

## 8. Parameter Discipline

The default use is the payload's configured parameter profile.

- Do not compare 9-26-52 and 5-13-26 outputs as if they were the same signal.
- Do not allow a faster intraday setting to override higher-timeframe context automatically.
- Any parameter change requires separate journaling/backtesting and a version label.

Example required metadata:

```json
{
  "ichimoku": {
    "parameter_profile": "9-26-52",
    "timeframe": "M5"
  }
}
```

If `parameter_profile` is missing, list it as missing data; do not assume a setting.

## 9. Required Payload Fields

Recommended minimal payload block:

```json
{
  "ichimoku": {
    "parameter_profile": "9-26-52",
    "timeframe": "M5",
    "price_vs_kumo": "above|below|inside|touching_top|touching_bottom|unknown",
    "kumo_direction": "bullish|bearish|neutral|unknown",
    "kumo_thickness_atr": null,
    "kumo_thickness_state": "thin|medium|thick|unknown",
    "tenkan": null,
    "kijun": null,
    "span_a": null,
    "span_b": null,
    "tenkan_vs_kijun": "bullish_cross|bearish_cross|bullish_aligned|bearish_aligned|neutral|unknown",
    "tk_cross_location": "above_kumo|below_kumo|inside_kumo|unknown",
    "tenkan_slope": "up|down|flat|unknown",
    "kijun_slope": "up|down|flat|unknown",
    "chikou_confirmation": "bullish_clear|bearish_clear|blocked|neutral|unknown",
    "kumo_breakout_state": "none|bullish_confirmed|bearish_confirmed|possible_false_breakout|unknown",
    "bar_confirmed": true
  }
}
```

All values must be calculated by Pine Script or a deterministic rule engine. The LLM must not infer missing Ichimoku facts from an image.

## 10. Filter Evaluation Procedure

Evaluate in this sequence:

1. Check payload validity and confirmed bar state.
2. Check whether `ichimoku` block and parameter profile exist.
3. Determine price position relative to Kumo.
4. Determine Kumo direction and thickness state if available.
5. Determine Tenkan–Kijun relationship and cross location.
6. Determine Chikou confirmation if available.
7. Check Kijun/line slope context if supplied.
8. Compare Ichimoku direction with Supply-Demand/Price Action, ICT/SMC, and BBMA proposed direction.
9. Return filter support/conflict/no-trade-zone status, missing data, and notes for the orchestrator.

## 11. Output Contract

Return valid JSON only. Do not use Markdown code fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "skill": "ichimoku-filter-playbook",
  "filter_status": "BULLISH_SUPPORT|BEARISH_SUPPORT|NEUTRAL|NO_TRADE_ZONE|FILTER_CONFLICT|MISSING_DATA",
  "timeframe": "string|null",
  "parameter_profile": "string|null",
  "regime": {
    "price_vs_kumo": "above|below|inside|touching_top|touching_bottom|unknown",
    "kumo_direction": "bullish|bearish|neutral|unknown",
    "kumo_thickness_state": "thin|medium|thick|unknown",
    "kumo_breakout_state": "none|bullish_confirmed|bearish_confirmed|possible_false_breakout|unknown"
  },
  "momentum": {
    "tenkan_vs_kijun": "bullish_cross|bearish_cross|bullish_aligned|bearish_aligned|neutral|unknown",
    "tk_cross_location": "above_kumo|below_kumo|inside_kumo|unknown",
    "tenkan_slope": "up|down|flat|unknown",
    "kijun_slope": "up|down|flat|unknown",
    "chikou_confirmation": "bullish_clear|bearish_clear|blocked|neutral|unknown"
  },
  "confluence": {
    "supports_buy": ["string"],
    "supports_sell": ["string"],
    "conflicts": ["string"],
    "neutral_notes": ["string"]
  },
  "filter_effect": {
    "proposed_direction": "buy|sell|null",
    "effect": "supports|downgrades|blocks|neutral",
    "reason": "string"
  },
  "dynamic_levels": {
    "kumo_top": null,
    "kumo_bottom": null,
    "kijun": null,
    "note": "Ichimoku levels are filter/context only; structural SL/TP comes from the risk and price-action layers."
  },
  "missing_data": ["string"],
  "manual_review_checklist": ["string"],
  "journal_seed": {
    "ichimoku_state": "string",
    "filter_effect": "supports|downgrades|blocks|neutral",
    "technical_lesson_candidate": "string|null"
  }
}
```

## 12. Paper Journal and Learning Rules

For each analysis, record when data exists:

- Ichimoku parameter profile and timeframe.
- Price relation to Kumo.
- Kumo direction and thickness state.
- Tenkan–Kijun relation/cross location.
- Chikou confirmation state.
- Kumo breakout state.
- Filter result: supports, downgrades, blocks, or neutral.
- Direction proposed by other skills.
- Final orchestrator status and outcome later.

Learning questions after sufficient sample size:

```text
- Do BBMA reentries perform differently above, below, or inside Kumo?
- Does price inside Kumo increase invalidations for the selected setup?
- Does Chikou confirmation improve outcomes enough to justify the added filter?
- Does thin Kumo correspond to more false breakouts for this instrument/timeframe?
- Does a given parameter profile help or add noise on M1/M3/M5?
```

The agent may propose a hypothesis, but may not alter parameters, filters, or strategy rules automatically.

## 13. Common Mistakes to Avoid

- Using Ichimoku as a standalone buy/sell strategy in this system.
- Treating price above Kumo as a guaranteed buy.
- Treating price below Kumo as a guaranteed sell.
- Taking TK crosses inside Kumo as strong signals.
- Calling cloud thick/thin without span and ATR data.
- Treating every Kumo breakout as valid without close/follow-through/structure confirmation.
- Letting Kijun override structural invalidation from OB/FVG/swing.
- Letting 30S Ichimoku create independent bias.
- Mixing results from different Ichimoku parameter profiles without labeling them.
- Letting an LLM infer Chikou/cloud relation from an unclear screenshot.
