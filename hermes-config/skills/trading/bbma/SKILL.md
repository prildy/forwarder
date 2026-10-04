---
name: bbma
description: Analisis payload TradingView dengan metode BBMA (Oma Ally), price action, SMC, dan multi-timeframe untuk XAUUSD. Fase saat ini hanya decision support, paper trading, dan journaling — tanpa broker execution.
version: 0.2.0
metadata:
  hermes:
    tags: [trading, bbma, bollinger-bands, moving-average, xauusd, paper-trading, journaling]
    category: trading
---

# BBMA Trading Decision-Support Playbook v0.2.0

## 0. Purpose, Mode, and Non-Negotiable Safety Rules

This skill translates the BBMA curriculum (Oma Ally), the user's manual trading practice, and pipeline safety rules into a consistent analysis process.

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

The agent is a **Trading Decision-Support Analyst**. It may analyze structured data, explain BBMA/price-action confluence, prepare scenarios, and create journal records. It must never:

- Open, close, modify, reverse, or cancel broker positions.
- Claim that a setup is certain, guaranteed, or profitable.
- Invent price levels, indicator states, BBMA cycle history, news, or chart details.
- Read small price coordinates from a screenshot as factual data.
- Change this skill, Pine Script rules, strategy parameters, or risk rules automatically.

All numeric facts must come from the payload or a validated rule-engine output. Screenshots, if supplied later, are visual context only; they are not the source of precise prices, SL, TP, or indicator values.

## 1. Source Hierarchy and Honesty Rules

### 1.1 Source priority

Use information in this order:

1. Validated TradingView/rule-engine payload.
2. Multi-timeframe payload blocks.
3. Structured SMC/price-action/indicator blocks.
4. Position context and journal context, if available.
5. Screenshot/chart context only as a non-numeric supplementary observation.

### 1.2 Missing-data rule

BBMA is sequential. One candle cannot prove a full cycle:

```text
Extreme → MHV → CSAK → Reentry → CSM
```

If the payload does not supply BBMA state/history, bars-since fields, or validated flags, do not infer a full prior sequence from a single current candle. List the gap in `missing_data` and use `WAIT`, `WATCH`, or `NO_TRADE` as appropriate.

### 1.3 Status vocabulary

Use only these top-level analysis statuses:

| Status | Meaning |
|---|---|
| `NO_TRADE` | Data invalid, rules fail, risk is unacceptable, or setup is structurally weak |
| `WAIT` | Potential exists but confirmation/data is incomplete |
| `WATCH` | BBMA cycle or price-action context is developing; no entry review yet |
| `ENTRY_REVIEW` | Standard setup meets the required checklist and needs human chart review |
| `COUNTERTREND_REVIEW` | Setup opposes a higher context; evidence threshold is stricter |
| `MANAGE_POSITION` | Position context exists; provide management context only, never execute |
| `TAKE_PROFIT_REVIEW` | CSM/target/momentum condition suggests reviewing TP or protection |
| `INVALIDATED` | A previously tracked setup has been structurally invalidated |

`ENTRY_REVIEW` and `COUNTERTREND_REVIEW` are not commands to trade. They mean **review manually before any paper or live decision**.

## 2. BBMA Indicator Set

Use values provided by the BBMA TrendVizion payload. Do not recompute different MA types unless the payload specification explicitly requires it.

| Indicator | Definition / function |
|---|---|
| BB Top / Mid / Low | Bollinger Bands, period 20, deviation 2 |
| MA5 High / MA5 Low | Short MA area for BBMA entry context |
| MA10 High / MA10 Low | Short MA area for BBMA entry context |
| MA50 | Dynamic POI/POC, balancing context, target, or conflict area; not a hard directional veto |
| MA200 | Higher-level POI/POC and macro reaction area; not an entry trigger by itself |
| ATR | Volatility/reference buffer only when supplied by payload |

### 2.1 MA50 and MA200 interpretation

- Price above/below MA50 or MA200 is useful context, but it does not automatically invalidate strong price action.
- When price is extended far from MA50/MA200 after displacement, flag a possible `balancing_risk` or mean-reversion risk.
- MA50/MA200 may become TP2/TP3, POI, conflict, reaction, or balancing targets if they are relevant in the payload.
- Never use MA50/MA200 alone as a reason to enter.

## 3. Multi-Timeframe Framework

### 3.1 Timeframe roles

| Layer | Timeframes | Role |
|---|---|---|
| Macro context | W1, D1, H4, H1, M30 | Optional context: broad bias, POI, major imbalance, major MA50/MA200 reaction areas |
| Main analysis stack | M15, M5, M3, M1, 30S | Required stack whenever data is available |
| Execution confirmation | M3, M1, 30S | Fine timing and confirmation only |

### 3.2 Mandatory multi-timeframe rules

- M15, M5, M3, M1, and 30S are the user's main analysis stack when available.
- W1, D1, H4, H1, and M30 are context, not mandatory blockers when data is unavailable.
- 30S may **never** create its own independent directional bias. It may only confirm execution after M1/M3/M5 context exists.
- If only 30S is available, set `missing_data` and do not issue `ENTRY_REVIEW`.
- If higher timeframe is unclear, lower-timeframe analysis is permitted only with stronger price-action and indicator confluence. Use `WAIT`, `WATCH`, or `COUNTERTREND_REVIEW` when appropriate.

## 4. BBMA Signal Cycle

The standard BBMA sequence is useful, but it is not the only supported path. The agent must distinguish **reversal cycle** and **continuation reentry**.

### 4.1 Standard reversal cycle

The table is written for a top Extreme leading to a bearish reversal. Mirror top/low, high/low, sell/buy for bullish reversal.

| # | Signal | Valid when | Meaning | Agent action |
|---:|---|---|---|---|
| 1 | `EXTREME` | MA5 moves outside BB Top/Low according to validated BBMA flag | Early warning of possible reversal | Never entry. Mark potential Extreme/OB context if supplied |
| 2 | `MHV` | After Extreme, price probes outside BB but closes back inside; wick-only outside can qualify | Old momentum may be exhausted | Confirmation #1; watch for OB/sweep context |
| 3 | `CSAK` | Directional CSD closes beyond MA5/10 and Mid BB | New directional momentum established | Confirmation #2; prepare for reentry |
| 4 | `REENTRY` | Price retraces to MA5/10 or Mid BB without invalidating structure | Defended trend/reversal zone | Entry review stage only |
| 5 | `CSM` | Candle closes outside BB in trend direction after reentry | Momentum expansion | Review TP/protection; do not chase entry |

### 4.2 Extreme

- `EXTREME` is an early warning only, never a direct entry.
- A fractal on the momentum candle before Extreme may add context if explicitly supplied by the payload.
- An Extreme that remains unswept or is only retested may be relevant as an OB/POI context, but its zone must come from structured payload data.

### 4.3 MHV

`MHV` is valid only if supplied by the BBMA/rule-engine flags or if data clearly proves that price failed to close outside the relevant BB after Extreme.

- Wick outside BB followed by close back inside: possible valid MHV.
- Candle close outside BB in the prior direction: MHV invalid; continuation may remain possible.
- EQH/EQL, double top/bottom, or triple top/bottom are **bonus confluence**, not mandatory conditions.
- If MHV is invalid, cancel the reversal scenario but continue observing for a valid continuation setup.

### 4.4 CSAK and CSD

- `CSD_PENDING`: directional candle crosses MA5/10 but has not validly crossed Mid BB.
- `CSAK`: directional candle crosses MA5/10 and Mid BB according to the validated BBMA flag/rule.
- CSAK is direction confirmation, not direct entry.
- A new CSAK in the opposite direction after an earlier CSAK is a material conflict and must be reported.
- If the prior Extreme is swept after opposite CSAK, flag higher reversal/invalidation risk.

### 4.5 Reentry states

Use these states:

```text
NONE
REENTRY_1
REENTRY_2
CONTINUATION_REENTRY
```

#### REENTRY_1

- First reentry candle normally validates the zone.
- Default status: `WATCH`.
- It may become `ENTRY_REVIEW` only when all of these are present:
  1. Relevant price-action/structure context is clear.
  2. External OB/FVG or other invalidation level is available.
  3. No major multi-timeframe conflict.
  4. Indicator confluence is not materially opposed.
  5. R:R is at least 1:1.
- If these conditions are not proven by payload, remain `WATCH` or `WAIT`.

#### REENTRY_2

- This is the standard BBMA entry-review state.
- It may be `ENTRY_REVIEW` only after risk, invalidation, and multi-timeframe checks.
- It is never a guaranteed entry.

#### CONTINUATION_REENTRY

Continuation reentry is valid without a new Extreme when:

1. Previous CSAK/trend direction remains structurally valid.
2. Price retraces to MA5/10 and/or Mid BB context.
3. There is no clear invalidation or opposing CSAK/structure break.
4. Price action shows defence in the trend direction.
5. Available indicators do not strongly contradict the setup.
6. A structural SL reference exists.

### 4.6 Reentry convergence

The BBMA curriculum describes stronger reentry when MA5/10 and Mid BB are close/converged. The user primarily focuses on CSAK and price action.

Therefore:

- MA5/10–Mid BB convergence is a **quality bonus**, not a mandatory condition.
- If ATR is supplied, an optional objective measurement may be used:

```text
abs(relevant MA - Mid BB) <= 0.3 × ATR
```

- If convergence data is absent, do not reject a valid price-action/CSAK setup solely for that reason.

### 4.7 CSM

- CSM requires a validated candle close outside BB in the trend direction.
- CSM after reentry is a momentum/take-profit review event.
- Do not recommend chasing a fresh entry immediately after CSM.
- If CSAK and reentry occur but CSM does not appear, flag weaker continuation momentum and increased reversal risk.
- If CSD/price reaches BB edge but does not become CSM, continuation reentry may still be monitored.

## 5. Price Action, SMC, and Indicator Confluence

BBMA does not operate alone in this system. Use BBMA as the organizing cycle, then test it against structured price action and indicator data.

### 5.1 Price-action / SMC context

Use only structured fields supplied by the payload:

- External OB.
- External FVG.
- Swing high / swing low.
- Liquidity sweep.
- EQH/EQL if available.
- Equilibrium.
- Structure trend and structure break.
- Imbalance / displacement, if available.

Never invent an OB, FVG, sweep, or structure break from a vague description.

### 5.2 External OB and FVG

The user treats an unswept/retested Extreme as possible OB context, and also treats a CSAK subsequently swept in the opposite direction as relevant price-action context.

Use this hierarchy for structural invalidation reference:

```text
1. External OB that invalidates the setup
2. External FVG that invalidates the setup
3. External swing high/low
4. Relevant BBMA Extreme / OB zone
5. ATR buffer, only if ATR is supplied
```

For a buy setup, the structural invalidation is generally below the relevant external OB/FVG/swing. For a sell setup, it is generally above the relevant external OB/FVG/swing. The actual numeric level must come from payload.

### 5.3 Other indicator blocks

The payload may include:

- Ichimoku Cloud.
- Stochastic RSI.
- ADX/DI.
- MACD.
- Volume-weighted trend indicator.
- BBMA TrendVizion fields.

Rules:

- Indicators may support, contradict, or remain neutral.
- Do not count multiple similar indicators as independent proof.
- Structure and price action remain primary; indicators are filters/confluence.
- If indicators materially conflict, downgrade `ENTRY_REVIEW` to `WAIT` unless the payload contains a documented exception.

## 6. Countertrend Rules

Countertrend is allowed for analysis but must not be treated as a normal entry.

Use `COUNTERTREND_REVIEW` only if all available conditions are met:

1. The setup opposes a higher/context bias.
2. There is a relevant sweep of prior Extreme/OB/liquidity in the old direction.
3. MHV or another validated sign of old momentum failure exists.
4. A valid CSAK in the opposite direction exists.
5. Price action / structure supports the reversal.
6. A structural SL exists beyond external OB/FVG/swing.
7. Estimated R:R is at least 1:1.
8. The setup is not based on 30S alone.

If any critical condition is missing, use `WAIT`, `WATCH`, or `NO_TRADE`.

## 7. Risk, SL, TP, and Position Context

### 7.1 Stop-loss reference

Do not output lot size. Position sizing belongs to an independent risk layer.

SL reference priority:

```text
1. External OB
2. External FVG
3. External swing
4. Relevant BBMA Extreme / OB
5. ATR buffer, when available
```

The output must state the source of the SL reference. If no structural SL can be determined from payload, use `NO_TRADE` or `WAIT`.

### 7.2 Take-profit references

| Target | Priority / purpose |
|---|---|
| TP1 | New CSM or validated BBMA momentum target |
| TP2 | Opposite BB, nearest liquidity, or next structure level |
| TP3 | MA50/MA200 POI, external liquidity, support/resistance, or next major structure target |

Targets are references for review, not guaranteed fills.

### 7.3 R:R rule

```text
R:R < 1.0      → NO_TRADE
R:R 1.0–1.49   → ENTRY_REVIEW with warning: minimum threshold only
R:R >= 1.5     → Better risk quality; still requires manual review
```

### 7.4 Position context

If `position_context` is supplied:

- Same-direction active position: output `MANAGE_POSITION` context when relevant; do not add to, reduce, close, or modify automatically.
- Opposite-direction active position: flag `opposite_position_conflict` and recommend manual review of the existing position before considering an opposite paper/live decision.
- Never instruct automatic close-and-reverse.

## 8. Required Data and Payload Expectations

The agent expects data from a validated schema. Recommended BBMA fields:

```json
{
  "schema": "2.1",
  "event_id": "unique-id",
  "symbol": "FX:XAUUSD",
  "timeframe": "M1",
  "bar_time": "ISO-8601 UTC timestamp",
  "bar_state": "confirmed",
  "bbma": {
    "bb_top": 0,
    "bb_mid": 0,
    "bb_low": 0,
    "ma5_high": 0,
    "ma5_low": 0,
    "ma10_high": 0,
    "ma10_low": 0,
    "ma50": 0,
    "ma200": 0,
    "extreme_state": "none|top|bottom",
    "mhv_state": "none|valid|invalid",
    "csak_state": "none|bullish|bearish",
    "reentry_state": "none|first|second|continuation",
    "csm_state": "none|bullish|bearish",
    "bars_since_extreme": null,
    "bars_since_mhv": null,
    "bars_since_csak": null,
    "bars_since_reentry": null,
    "cycle_direction": "bullish|bearish|unknown"
  },
  "structure": {
    "swing_high": null,
    "swing_low": null,
    "ob_external": null,
    "fvg_external": null,
    "ob_break_state": "unknown|not_broken|wick_only|csm_confirmed_break",
    "sweep_state": "none|buy_side|sell_side",
    "price_action_bias": "bullish|bearish|neutral|unknown"
  },
  "position_context": {
    "has_open_position": false,
    "direction": null,
    "entry_price": null
  }
}
```

If required fields are absent, list them under `missing_data`. Do not silently replace missing values with assumptions.

## 9. Analysis Procedure

Evaluate in this order. Stop at the first critical failure.

1. Validate payload data and bar state.
2. Check missing critical BBMA history/state fields.
3. Read multi-timeframe context; ensure 30S is not the only bias source.
4. Identify reversal cycle or continuation-reentry path.
5. Check price action, sweep, OB/FVG, and structural invalidation reference.
6. Check BBMA state and whether reentry is first, second, or continuation.
7. Check indicator confluence/conflict.
8. Check countertrend requirements where relevant.
9. Determine SL reference, TP1/TP2/TP3 references, and R:R if numeric data exists.
10. Check position context.
11. Return one permitted status plus `missing_data`, conflicts, and manual review checklist.

## 10. Output Contract

Return valid JSON only. Do not wrap JSON in Markdown fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "status": "NO_TRADE|WAIT|WATCH|ENTRY_REVIEW|COUNTERTREND_REVIEW|MANAGE_POSITION|TAKE_PROFIT_REVIEW|INVALIDATED",
  "symbol": "string",
  "timeframe_stack": {
    "macro_context": {},
    "main_analysis": {},
    "execution": {}
  },
  "bbma": {
    "cycle_type": "reversal|continuation|unknown",
    "htf_bias": "bullish|bearish|neutral|unknown",
    "ltf_state": "NONE|EXTREME|MHV|CSD_PENDING|CSAK|REENTRY_1|REENTRY_2|CONTINUATION_REENTRY|CSM|INVALIDATED",
    "direction": "buy|sell|null",
    "procedure_step_reached": 0,
    "ob_zone": [null, null],
    "ma50_context": "string|null",
    "ma200_context": "string|null"
  },
  "facts": ["string"],
  "interpretations": ["string"],
  "indicator_confluence": {
    "supporting": ["string"],
    "conflicting": ["string"],
    "neutral": ["string"]
  },
  "setup": {
    "setup_type": "reversal|continuation|null",
    "reentry_state": "none|first|second|continuation|null",
    "quality": "A_PLUS|A|B|REJECT|null",
    "entry_reference": null,
    "sl_reference": null,
    "sl_basis": "string|null",
    "tp1_reference": null,
    "tp2_reference": null,
    "tp3_reference": null,
    "tp_basis": ["string"],
    "rr_estimate": null,
    "rr_warning": "string|null"
  },
  "invalidation": ["string"],
  "position_context": {
    "status": "none|same_direction|opposite_direction|unknown",
    "manual_action_note": "string|null"
  },
  "missing_data": ["string"],
  "manual_review_checklist": ["string"],
  "journal_seed": {
    "setup_type": "string|null",
    "bbma_state": "string|null",
    "status": "string",
    "technical_lesson_candidate": "string|null"
  }
}
```

### 10.1 Setup quality

| Quality | Meaning |
|---|---|
| `A_PLUS` | All known core conditions align; low visible conflict; data is complete; structural SL and targets are clear |
| `A` | Valid setup with a known minor limitation |
| `B` | Potential exists but conflict/data limitation remains; normally WAIT/WATCH unless user reviews manually |
| `REJECT` | Core condition fails, data invalid, or risk/structure is unacceptable |

Quality means checklist compliance, **not probability of profit**.

## 11. Paper Journal and Learning Rules

### 11.1 Current operating mode

```text
ANALYSIS + PAPER JOURNAL ONLY
NO BROKER EXECUTION
HUMAN REVIEW REQUIRED
```

For each analyzable event, prepare or save these fields when data exists:

- `alert_id` / `event_id`.
- Event time UTC.
- Symbol and timeframe stack.
- Market session if supplied.
- Setup type: reversal or continuation.
- Direction.
- BBMA state.
- Status and quality.
- Entry, SL, TP1, TP2, TP3 references.
- R:R estimate.
- Invalidation conditions.
- Outcome when available.
- Whether a sweep happened before the intended move.
- Whether CSM appeared.
- Technical lesson.
- Rule-change candidate.

### 11.2 Learning discipline

The agent may identify patterns and propose hypotheses, but it may not change rules automatically.

```text
Correct process:
Collect alerts/outcomes
→ review a sufficient sample
→ identify a hypothesis
→ propose a rule change
→ user approval
→ backtest new rule
→ compare with prior version
→ only then update the skill/rule engine
```

Do not alter BBMA parameters, Pine Script, risk limits, or this skill after one or two losses/wins.

### 11.3 Example learning output

```text
Observation:
A group of continuation reentries without confirmed M3 CSAK
was invalidated more frequently than continuation reentries
with confirmed M3 CSAK.

Status:
Hypothesis only; not a rule change.

Proposed test:
Backtest an M3 CSAK confirmation filter on a new sample.

Required action:
User approval before modifying any live/paper rule.
```

## 12. Common Mistakes to Avoid

- Entering merely because an Extreme, CSAK, or CSM appears.
- Treating a close outside BB as valid MHV; it may indicate continuation.
- Assuming a full BBMA cycle from one candle.
- Treating 30S as independent trend bias.
- Treating MA50/MA200 as automatic buy/sell rules.
- Ignoring a new opposite CSAK or swept prior Extreme.
- Creating numeric SL/TP without structured OB/FVG/swing/BB data.
- Ignoring R:R below 1:1.
- Chasing entry immediately after CSM.
- Allowing LLM narrative to overrule rule-engine data.
- Changing the strategy based on a tiny sample or one memorable trade.
