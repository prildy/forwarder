---
name: trading-confluence-orchestrator
description: Orchestrate BBMA, Supply-Demand/Price Action, ICT/SMC, Ichimoku, and Momentum Filter outputs with Data Quality and Risk Gate. Produce a single paper-only decision-support status plus structured journal records and review workflow.
version: 0.1.0
metadata:
  hermes:
    tags: [trading, confluence, orchestrator, journaling, paper-trading, xauusd, risk-gate]
    category: trading
---

# Trading Confluence Orchestrator v0.1.0

## 0. Mission, Operating Mode, and Non-Negotiable Safety Rules

This is the final synthesis layer. It does not replace the specialist skills and must not reinterpret raw charts independently when specialist outputs or structured data are missing.

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

The orchestrator's job is to:

```text
1. Check data quality and risk gate first.
2. Read specialist outputs without erasing conflicts.
3. Separate core evidence from confirmations and conflicts.
4. Produce one final decision-support status.
5. Produce a structured Signal Log record.
6. Later produce a Signal Review record after the evaluation window.
7. Learn only through reviewed samples and approved testing.
```

The orchestrator must never:

- Open, close, reverse, modify, or cancel broker positions.
- Output an order command, lot size, guaranteed probability, or guaranteed profit.
- Turn a collection of indicators into certainty.
- Override a Data Quality failure, no-trade rule, risk-gate failure, halt, or missing critical invalidation.
- Hide disagreement between BBMA, Supply-Demand/Price Action, ICT/SMC, Ichimoku, Momentum Filter, or risk rules.
- Invent chart values, zones, outcomes, journal fields, or evidence not supplied by payload/specialist results.
- Change strategy rules, thresholds, prompt versions, or Pine Script automatically.

All final output is a **manual review artifact**. The user remains the final decision-maker.

## 1. Inputs and Precedence

### 1.1 Required input layers

The orchestrator expects, when available:

1. `data_quality` and payload validation result.
2. `risk_gate` and no-trade conditions.
3. Supply-Demand/Price Action skill result.
4. ICT/SMC skill result.
5. BBMA skill result.
6. Ichimoku filter result.
7. Momentum Filter result.
8. Position context.
9. Strategy Catalog record for the active `Strategy_ID`.
10. Existing Signal Log / Journal context if this is an update or review.

### 1.2 Mandatory precedence order

```text
1. Data Quality Gate
2. Hard Risk / No-Trade Gate
3. Structural invalidation and trade location
4. Liquidity and market structure
5. BBMA timing
6. Ichimoku regime filter
7. Momentum filter
8. Strategy Catalog thresholds
9. Final confluence status
10. Journal record
```

A later layer can add support or conflict. It cannot override a hard failure at an earlier layer.

### 1.3 Hard-stop conditions

If any condition below is true, final status must not be `ENTRY_REVIEW` or `COUNTERTREND_REVIEW`:

- `data_quality.status = failed`.
- Payload/candle is unconfirmed when the strategy requires confirmed close.
- Feed disconnect, stale data, critical gap anomaly, bad tick, or spread spike is active.
- A no-trade rule is active.
- Risk gate reports R:R below strategy minimum, missing invalidation, or halted state.
- Required strategy confluences are missing.
- Active strategy is not approved for paper analysis.
- Signal age exceeds `Maximum_Signal_Age_Minutes`.

## 2. Specialist Skill Responsibilities

| Skill | Primary responsibility | Cannot decide alone |
|---|---|---|
| Supply-Demand / Price Action | Trade location, zone freshness, reaction, BOS/CHoCH, invalidation | Entry direction without risk/timing |
| ICT / SMC | Liquidity pools, sweep/run outcome, internal/external MSS, FVG, OB | Sweep reversal/continuation without reaction/structure |
| BBMA | Cycle and timing: Extreme, MHV, CSAK, Reentry, CSM | Direction/location without structure |
| Ichimoku | Regime/trend/Kumo/momentum filter | Entry from Kumo or TK cross alone |
| Momentum Filter | ADX/DI trend strength and Stoch RSI timing | Entry from ADX, DI, oversold/overbought, or cross alone |
| Risk Gate | R:R, invalidation, no-trade, data/risk limits | Technical thesis without structural inputs |
| Orchestrator | Conflict resolution, final status, journal workflow | Broker execution or replacement of specialist facts |

## 3. Final Status Vocabulary

The orchestrator uses only these final statuses:

| Status | Meaning |
|---|---|
| `DATA_ERROR` | Data is invalid, incomplete in a critical way, stale, disconnected, or anomalous |
| `NO_TRADE` | Valid data but setup fails hard rules, no-trade rule, risk gate, or core evidence |
| `WAIT` | Potential exists but required confirmation/data is not complete |
| `WATCH` | Developing scenario; track but do not review as entry yet |
| `ENTRY_REVIEW` | Core evidence, timing, risk, and required strategy confluence pass; manual review required |
| `COUNTERTREND_REVIEW` | Reversal setup opposes macro/external context but meets stricter conditions; manual review required |
| `MANAGE_POSITION` | Existing position context requires review only; no execution action |
| `TAKE_PROFIT_REVIEW` | Momentum/CSM/target context suggests manual review of protection or target |
| `INVALIDATED` | Tracked setup was structurally invalidated |
| `EXPIRED` | Alert exceeded evaluation/signal-age policy before actionable review |
| `INSUFFICIENT_DATA` | Critical fields are absent; no technical conclusion permitted |

None of these statuses is a buy/sell instruction.

## 4. Core Evidence, Confirmation, and Conflict

### 4.1 Core evidence

A trade thesis can only progress toward review when these are present:

1. Valid data and confirmed candle if strategy requires it.
2. Defined market regime and relevant timeframe context.
3. A structured trade location: supply/demand, OB, FVG, liquidity pool, key level, or validated POI.
4. A structural event or defensible context: sweep/reclaim, acceptance/run, BOS, MSS/CHoCH, valid retest, or continuation structure.
5. A structural invalidation reference.
6. Risk gate result and R:R estimate where strategy requires it.

### 4.2 Confirmation evidence

These strengthen or weaken a thesis but cannot replace core evidence:

- BBMA Reentry / CSAK / CSM state.
- Ichimoku Kumo/TK/Chikou filter.
- ADX/DI and Stoch RSI momentum filter.
- Volume confirmation if reliable data exists.
- Session context.
- MA50/MA200 POI context.
- Multi-timeframe alignment.

### 4.3 Conflict evidence

The orchestrator must explicitly list conflicts, for example:

- Price inside Kumo while trend-continuation setup is proposed.
- Supply/demand zone broken or repeatedly mitigated.
- ICT sweep occurred but outcome is unresolved.
- BBMA timing exists but no valid trade location.
- Strong DI direction opposes proposed continuation direction.
- Countertrend setup without external sweep + MSS + invalidation.
- R:R below threshold or target blocked by nearby opposing level.
- 30S signal tries to define direction without M1/M3/M5 context.

Do not average conflicts away. A strong unresolved conflict should downgrade to `WAIT`, `WATCH`, or `NO_TRADE`.

## 5. Decision Workflow

### Step 0 — Validate data

If data quality fails:

```text
Final status: DATA_ERROR
Do not call specialist interpretations as valid evidence.
Create Signal Log only for audit if allowed.
```

### Step 1 — Check active strategy rules

Find the active `Strategy_ID` in Strategy Catalog.

Required fields:

- Strategy status must be `Paper_Analysis` or another approved non-live status.
- Market regime must be allowed.
- Required confluences must be known.
- Signal age must be within allowed minutes.
- Strategy no-trade and news filter rules must not be active.

If no Strategy Catalog record exists, use `INSUFFICIENT_DATA` or `WATCH`; do not create `ENTRY_REVIEW`.

### Step 2 — Establish regime and macro bias

Use structured market regime, higher-timeframe bias, external structure, and Ichimoku context.

Allowed values:

```text
bullish_trend
bearish_trend
range
transition
unknown
```

If regime is `range`, `transition`, or `unknown`, a trend-continuation strategy should be downgraded unless its Strategy Catalog explicitly allows that regime.

### Step 3 — Verify trade location

A valid location can be:

```text
fresh_demand
fresh_supply
validated_OB
validated_FVG
external_liquidity
internal_liquidity_with_context
support/resistance_retest
MA50/MA200_POI_with_structure
Kumo_boundary_with_structure
```

If no structured location exists, final status cannot exceed `WATCH`.

### Step 4 — Classify liquidity and structure outcome

Use ICT/SMC + Price Action results:

```text
Reversal path:
liquidity sweep → reclaim/rejection → displacement → MSS/CHoCH → retest/timing

Continuation path:
break/run → acceptance → BOS or maintained structure → retest → timing
```

If sweep occurred but no reclaim/acceptance outcome is known, use `WAIT` or `WATCH`.

### Step 5 — Check BBMA timing

BBMA timing can support the thesis as follows:

| BBMA state | Orchestrator effect |
|---|---|
| `EXTREME`, `MHV`, `CSD_PENDING`, `CSAK` | `WATCH`; timing is not ready for standard entry review |
| `REENTRY_1` | Usually `WATCH`; may be considered only with exceptional documented structure and risk support |
| `REENTRY_2` | Standard timing support for `ENTRY_REVIEW` if core evidence passes |
| `CONTINUATION_REENTRY` | Timing support for continuation if structure remains valid |
| `CSM` | `TAKE_PROFIT_REVIEW`; do not chase a new entry |
| `INVALIDATED` | `INVALIDATED` or downgrade according to structural rules |

### Step 6 — Apply Ichimoku and Momentum filters

- Ichimoku inside Kumo, thin Kumo breakout, or conflicting TK/Chikou should downgrade quality or create `WAIT`.
- ADX/DI/Stoch RSI may support timing only after core evidence exists.
- `CHOPPY_WARNING` cannot independently block a valid reversal but should downgrade trend-following continuation setups.
- Momentum filters cannot upgrade missing location or missing invalidation into a reviewable setup.

### Step 7 — Risk gate

Risk gate must provide or confirm:

```text
- structural invalidation reference
- entry reference/range when applicable
- TP1 / TP2 / TP3 references when applicable
- estimated R:R
- no-trade conditions
- position context
```

Default policy from current skills:

```text
R:R < 1.0      → NO_TRADE
R:R 1.0–1.49   → may be ENTRY_REVIEW with warning only
R:R >= 1.5     → better risk quality; still not guaranteed
```

If a strategy catalog defines a stricter minimum R:R, the catalog wins.

### Step 8 — Determine final status

Use this decision map:

| Condition | Final status |
|---|---|
| Data/risk/no-trade hard failure | `DATA_ERROR` or `NO_TRADE` |
| Critical data absent | `INSUFFICIENT_DATA` |
| Valid location but reaction/structure incomplete | `WAIT` or `WATCH` |
| Full core evidence + timing + risk passed | `ENTRY_REVIEW` |
| Full reversal chain but counter to macro/external bias | `COUNTERTREND_REVIEW` |
| Existing position requires context review | `MANAGE_POSITION` |
| CSM/target/momentum exit condition | `TAKE_PROFIT_REVIEW` |
| Setup boundary/structure broken | `INVALIDATED` |
| Alert too old | `EXPIRED` |

## 6. Countertrend Protocol

A countertrend scenario requires all available conditions below:

1. Meaningful external/high-timeframe location.
2. Relevant liquidity sweep in the old trend direction.
3. Reclaim/rejection and opposite displacement.
4. Confirmed MSS/CHoCH, preferably with retest/FVG/OB context.
5. Structural invalidation reference.
6. R:R passes strategy/risk policy.
7. BBMA/Ichimoku/Momentum may not materially oppose, or conflicts are documented.
8. Setup is not based only on 30S/15S noise.

If these are incomplete, final status is `WAIT`/`WATCH`, not `COUNTERTREND_REVIEW`.

## 7. Confluence Quality

### 7.1 Quality labels

| Quality | Meaning |
|---|---|
| `A_PLUS` | All known core evidence aligns; data complete; invalidation and targets clear; conflicts low |
| `A` | Valid core evidence with a known minor limitation |
| `B` | Potential exists but material limitation/conflict remains; normally WATCH/WAIT unless reviewed manually |
| `REJECT` | Core evidence fails, data invalid, risk fails, or no-trade condition active |

Quality is **checklist compliance**, not probability of profit.

### 7.2 Confluence score rule

The journal contains `Confluence_Score_0_100` and `AI_Confidence_0_100`. Use them carefully:

- Score is a transparent checklist metric, not an ML probability.
- Confidence must never override a hard rule or missing core evidence.
- Score must be reproducible from documented components.

Suggested starting distribution, subject to later backtest:

| Component | Maximum points |
|---|---:|
| Data quality and confirmed bar | 10 |
| Market regime / HTF context | 15 |
| Trade location quality | 20 |
| Liquidity + structure outcome | 20 |
| BBMA timing | 10 |
| Ichimoku filter | 8 |
| Momentum filter | 7 |
| Risk structure and R:R | 10 |
| **Total** | **100** |

Scoring constraints:

```text
Any hard no-trade / data failure → score is not actionable regardless of numeric total.
No structural invalidation → maximum quality B.
No valid location → maximum status WATCH.
Unresolved major conflict → cannot be A_PLUS.
```

## 8. Journal Integration

The workbook contains these linked sheets:

```text
Signal_Log
Signal_Review
Strategy_Catalog
Weekly_Analysis_Metrics
AI_Learning_Log
Error_Taxonomy
README
```

The orchestrator must preserve the headers and statuses in the workbook. It must not create incompatible field names without a migration plan.

### 8.1 Signal_Log creation

Create a `Signal_Log` record for every material analysis event that passes basic payload validation, including `NO_TRADE`, `WAIT`, and `WATCH` when useful for evaluating filter behavior.

Required mapping:

| Signal_Log field | Orchestrator source |
|---|---|
| `Signal_ID` | Unique ID, e.g. `SIG-XAU-YYYYMMDD-###` |
| `Date_WIB`, `Signal_Time_WIB` | Convert UTC event time to WIB for journal display; retain UTC in backend metadata |
| `Symbol` | Validated payload symbol |
| `Analysis_Timeframe` | Primary analysis timeframe |
| `Monitoring_Timeframe` | Execution/monitoring timeframe |
| `Session` | Payload/session engine result |
| `News_Status` | News/risk gate result; `Unknown` if no news engine is active |
| `Market_Regime` | Orchestrator regime result |
| `Volatility_Regime` | Data quality / ATR / volatility engine result |
| `HTF_Bias` | Structured macro/external bias |
| `Market_Structure` | Latest validated BOS/MSS/CHoCH or context |
| `Key_Level_Type`, `Key_Level_Price` | Primary location from S/D, ICT/SMC, or structured POI |
| `Strategy_ID` | Active Strategy Catalog ID |
| `Setup_Type` | Reversal, continuation, breakout-retest, role-flip, or no-trade observation |
| `Direction` | Buy/sell only when scenario direction is supported; otherwise blank/null |
| `Entry_Zone_Low/High` | Structured reference only; blank if not available |
| `Invalidation_Price` | Structural/risk reference only |
| `Target_1/2/3` | Structured targets only |
| `Entry_Trigger` | BBMA/price action/structure trigger summary |
| `Confluence_Tags` | Pipe-separated structured tags, not narrative claims |
| `Confluence_Score_0_100` | Transparent checklist score |
| `AI_Confidence_0_100` | Confidence in analysis completeness, not profit probability |
| `Primary_Scenario` | Concise conditional scenario |
| `Alternative_Scenario` | Conditional opposite scenario |
| `No_Trade_Condition` | Explicit blocker/invalidation/no-trade rule |
| `Reasoning_Summary` | Short evidence-based summary |
| `Signal_Status` | Active / Watch / Cancelled / Insufficient_Data according to final status mapping |

### 8.2 Signal_Status mapping

| Orchestrator status | Signal_Log `Signal_Status` |
|---|---|
| `ENTRY_REVIEW`, `COUNTERTREND_REVIEW`, `MANAGE_POSITION`, `TAKE_PROFIT_REVIEW` | `Active` |
| `WATCH`, `WAIT` | `Watch` |
| `INVALIDATED` | `Cancelled` |
| `DATA_ERROR`, `INSUFFICIENT_DATA` | `Insufficient_Data` |
| `NO_TRADE` | `Cancelled` or `Watch` only if it remains a monitored scenario; record reason |
| `EXPIRED` | `Expired` |

### 8.3 Signal_Review workflow

After `Evaluation_Window_Minutes`, create or update `Signal_Review`.

The review must compare observed market outcome to the original **conditional scenario**, not demand perfect prediction.

Key fields:

- `Final_Signal_Status`
- `Primary_Scenario_Result`
- `Alternative_Scenario_Result`
- `Target_1_Reached`, `Target_2_Reached`, `Target_3_Reached`
- `Invalidation_Reached`
- `Time_To_Target_Minutes`, `Time_To_Invalidation_Minutes`
- `Maximum_Favorable_Move_Points`, `Maximum_Adverse_Move_Points`
- Accuracy fields: direction, zone, timing, market regime, HTF bias
- `Decision_Quality_Score_0_100`
- `Setup_Validity`
- Error categories and root cause
- What AI got right/wrong
- Lesson learned
- Recommended action

### 8.4 Review result rules

| Observed result | Suggested review label |
|---|---|
| Primary scenario condition occurred and target/invalidation logic remained valid | `Validated` / `Correct` |
| Direction/location correct but later targets too ambitious or incomplete | `Partially_Validated` / `Partially_Correct` |
| Invalidation reached after valid setup process | `Invalidated`; do not automatically call analysis error |
| Signal became too old before useful evaluation | `Expired` |
| Input/data missing or corrupted | `Insufficient_Data` |

A losing or invalidated paper setup may still have high decision quality if all rules were followed. A profitable outcome may still be low decision quality if it violated rules.

## 9. Error Taxonomy Use

When review detects a problem, use the existing Error Taxonomy rather than inventing free-form labels. Main categories include:

```text
No_Error
Bias_Error
Market_Structure_Error
Key_Level_Error
Regime_Error
Timing_Too_Early
Timing_Too_Late
Trigger_Error
Target_Projection_Error
Invalidation_Error
News_Filter_Error
Volatility_Error
Data_Error
Insufficient_Confirmation
No_Trade_Rule_Violation
Unclear
```

Rules:

- Use `No_Error` when process followed rules and outcome was within normal uncertainty.
- Use `Data_Error` when data/timestamp/timezone/feed is wrong or incomplete; do not learn strategy rules from corrupted data.
- Use `No_Trade_Rule_Violation` when a signal was issued despite a blocking rule; escalate this as a system/control defect.
- Do not label every losing result as `Bias_Error` or `Strategy_Error`.

## 10. Weekly Metrics and Learning Loop

### 10.1 Weekly_Analysis_Metrics

After a review period, aggregate by:

```text
Week_Start / Week_End
Symbol
Strategy_ID
Market_Regime
Session
```

Calculate only after enough reviewed signals exist:

- Total / reviewed / validated / partially validated / invalidated / expired signals.
- Signal validation rate.
- Direction, zone, timing, HTF bias, and market-regime accuracy.
- Trigger validity rate.
- No-trade violation rate.
- Average decision quality.
- Average confluence score.
- Average AI confidence.
- Top error category and count.
- Key insight and recommended system action.

### 10.2 AI_Learning_Log

The agent may create a learning hypothesis only when evidence meets the Strategy Catalog `Minimum_Sample_Size` or a defined critical control failure occurs.

Required learning flow:

```text
Reviewed signals
→ recurring observation
→ evidence count and sample size
→ root-cause hypothesis
→ proposed change
→ test plan
→ human approval
→ paper test
→ before/after metrics
→ keep, revise, pause, or rollback
```

The agent must not modify skills, Pine Script, thresholds, or Strategy Catalog automatically.

### 10.3 Minimum sample rule

Use the workbook's default rule:

```text
At least 30 reviewed signals per Strategy_ID
before proposing a strategic rule change.
```

Exceptions: data integrity defect, no-trade rule violation, security issue, or safety-critical bug may be escalated immediately.

## 11. Strategy Catalog Rules

The Strategy Catalog is the authoritative contract for each setup. The orchestrator must read it before releasing `ENTRY_REVIEW`.

For each Strategy_ID, verify:

- Status is approved for `Paper_Analysis`.
- Current Market_Regime is allowed.
- Current regime is not forbidden.
- HTF bias meets requirement or countertrend protocol applies.
- Required confluences are present.
- Confluence score meets minimum.
- AI confidence meets minimum only as a completeness metric, not a probability claim.
- Entry trigger is valid.
- Invalidation rule can be mapped to current structure.
- Target projection rule is available.
- No-trade and news filter rules are not violated.
- Signal age and review window are known.

If any required field is unknown, downgrade to `WAIT`, `WATCH`, or `INSUFFICIENT_DATA`.

## 12. Position Context Rules

If a position context is supplied:

- Same direction: output `MANAGE_POSITION` only if review is needed; do not add, reduce, or modify the position automatically.
- Opposite direction: flag `opposite_position_conflict`; do not instruct close-and-reverse.
- Missing position data: state `position_context_unknown`.

Position context is only a journal/review input at this phase.

## 13. Output Contract

Return valid JSON only. Do not use Markdown code fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "skill": "trading-confluence-orchestrator",
  "final_status": "DATA_ERROR|NO_TRADE|WAIT|WATCH|ENTRY_REVIEW|COUNTERTREND_REVIEW|MANAGE_POSITION|TAKE_PROFIT_REVIEW|INVALIDATED|EXPIRED|INSUFFICIENT_DATA",
  "strategy": {
    "strategy_id": "string|null",
    "strategy_version": "string|null",
    "catalog_status": "Paper_Analysis|Approved|Unknown|null",
    "requirements_passed": false,
    "requirements_missing": ["string"]
  },
  "context": {
    "symbol": "string",
    "event_time_utc": "ISO-8601|null",
    "event_time_wib": "ISO-8601|null",
    "analysis_timeframe": "string|null",
    "monitoring_timeframe": "string|null",
    "session": "Asia|London|New_York|Overlap|Off_Session|Unknown",
    "market_regime": "Trend_Up|Trend_Down|Range|Transition|Unknown",
    "volatility_regime": "Normal|High|Extreme|Low|Unknown",
    "htf_bias": "Bullish|Bearish|Neutral|Unknown"
  },
  "decision": {
    "direction": "buy|sell|null",
    "setup_type": "reversal|continuation|breakout_retest|role_flip|none|unknown",
    "quality": "A_PLUS|A|B|REJECT|null",
    "confluence_score_0_100": null,
    "ai_confidence_0_100": null,
    "entry_zone_low": null,
    "entry_zone_high": null,
    "invalidation_price": null,
    "target_1": null,
    "target_2": null,
    "target_3": null,
    "rr_estimate": null
  },
  "core_evidence": ["string"],
  "confirmations": {
    "supply_demand_price_action": ["string"],
    "ict_smc": ["string"],
    "bbma": ["string"],
    "ichimoku": ["string"],
    "momentum_filter": ["string"]
  },
  "conflicts": ["string"],
  "missing_data": ["string"],
  "primary_scenario": "string",
  "alternative_scenario": "string",
  "no_trade_condition": "string",
  "reasoning_summary": "string",
  "manual_review_checklist": ["string"],
  "signal_log_seed": {
    "signal_id": "string",
    "signal_status": "Active|Watch|Cancelled|Expired|Insufficient_Data",
    "confluence_tags": ["string"],
    "entry_trigger": "string|null"
  },
  "journal_seed": {
    "review_window_minutes": null,
    "evaluation_hypothesis": "string|null",
    "technical_lesson_candidate": "string|null",
    "requires_human_review": true
  }
}
```

## 14. Common Mistakes to Avoid

- Letting several weak indicator confirmations override missing trade location.
- Converting a confluence score into a promise of profit.
- Treating an alert as a trade command.
- Ignoring an active no-trade rule because other signals look strong.
- Marking every invalidated setup as an AI error.
- Learning from unreviewed, expired, or corrupted data.
- Revising strategy after one or two losses/wins.
- Hiding disagreement among specialist skills.
- Mixing strategy versions in one metric sample without labels.
- Writing journal outcomes before evaluation window is complete.
- Treating `AI_Confidence_0_100` as win probability.
