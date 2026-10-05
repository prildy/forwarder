---
name: ict-smc-playbook
description: Analyze validated TradingView and rule-engine payloads with a staged ICT/SMC framework: liquidity, sweep, MSS/CHoCH, FVG, and Order Block. This skill maps order-flow context for paper-only decision support; it never executes broker actions.
version: 0.1.0
metadata:
  hermes:
    tags: [trading, ict, smc, liquidity, sweep, mss, choch, fvg, order-block, xauusd, paper-trading]
    category: trading
---

# ICT / SMC Decision-Support Playbook v0.1.0

## 0. Purpose, Scope, and Safety Rules

This skill introduces ICT/SMC in stages. Version 0.1.0 is intentionally limited to:

```text
1. Liquidity
2. Liquidity sweep / liquidity run
3. MSS / CHoCH and BOS context
4. Fair Value Gap (FVG) / imbalance
5. Order Block (OB)
```

It does not yet make kill zones, Judas Swing, OTE, breaker blocks, mitigation blocks, market-maker models, DOM, tape reading, or footprint data mandatory rules. Those can be added only after the first five concepts are defined, encoded, and journaled reliably.

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

The agent may map liquidity, identify structured sweep/continuation/reversal sequences, and provide context to other skills. It must never:

- Open, close, reverse, modify, or cancel broker positions.
- Claim that liquidity is certain to be taken, swept, filled, or reversed.
- Treat every EQH/EQL, high/low, FVG, or opposite candle as a valid trade location.
- Invent liquidity pools, swings, sweeps, MSS, BOS, FVGs, OBs, or session events from a screenshot or incomplete payload.
- Treat an ICT/SMC label alone as an entry signal.
- Override Data Quality Gate, Risk Engine, Supply-Demand/Price Action invalidation, BBMA timing, or human review.
- Change rule definitions or parameters automatically based on a small sample.

All facts must come from validated payload/rule-engine fields. Screenshots are only non-numeric supplementary context.

## 1. Role in the Multi-Skill System

| Framework | Primary role |
|---|---|
| Supply-Demand & Price Action | Zone quality, price-action reaction, BOS/CHoCH validation, structural invalidation |
| **ICT/SMC** | Liquidity map, sweep outcome, internal/external structure, FVG and OB context |
| BBMA | Timing cycle: Extreme, MHV, CSAK, Reentry, CSM |
| Ichimoku | Regime/trend/momentum filter |
| Rule/Risk Engine | Data quality, cooldown, R:R, risk limits, WAIT/NO_TRADE/HALTED |
| Confluence Orchestrator | Combines all support/conflict and returns final decision-support status |

This skill does not produce a broker order. It outputs liquidity and structure context, plus a filter status for the orchestrator.

## 2. Source Hierarchy and Honesty Rules

Use evidence in this order:

1. Validated TradingView/rule-engine payload.
2. Structured multi-timeframe fields.
3. Structured liquidity pool, swing, sweep, structure, FVG, and OB fields.
4. Session metadata if supplied.
5. Screenshot only as non-numeric supporting context.

If data is missing, say so. Examples:

```text
No swing/high-low source → do not label external liquidity.
No close/reaction data after level break → do not call reversal or continuation.
No three-candle FVG fields → do not invent an FVG.
No validated OB record → do not call last opposite candle an OB.
No internal/external scope → do not upgrade minor MSS to major reversal.
No session/timestamp → do not claim a London/NY kill-zone event.
```

## 3. Status Vocabulary

Use only the following ICT/SMC skill-layer statuses:

| Status | Meaning |
|---|---|
| `NO_TRADE` | Data invalid, no structured location, invalidation missing, or core structure contradicts the idea |
| `WAIT` | Liquidity/structure event is incomplete or confirmation is missing |
| `WATCH` | Liquidity pool, FVG, OB, or possible sweep is developing; no review yet |
| `LIQUIDITY_REVIEW` | A meaningful liquidity/PD-array location exists; wait for reaction/structure/timing confirmation |
| `CONTINUATION_REVIEW` | Sweep/break, displacement/BOS, and retest context support trend continuation; still needs other skills/risk review |
| `REVERSAL_REVIEW` | Sweep + reaction + MSS/CHoCH support reversal; may be countertrend and needs strict review |
| `COUNTERTREND_REVIEW` | Reversal context opposes higher structure; evidence threshold is stricter |
| `INVALIDATED` | OB/FVG/structure scenario is broken by confirmed rule-engine conditions |

These are analytical states, not trade instructions.

## 4. Objective ICT/SMC Vocabulary

### 4.1 Liquidity

Liquidity is a structured potential concentration of resting orders around visible price references. It is a **map and possible draw**, not a prediction that price must touch it.

| Term | Structured definition |
|---|---|
| `buy_side_liquidity` / BSL | Liquidity above current price, e.g. EQH, obvious high, previous/session high, external swing high |
| `sell_side_liquidity` / SSL | Liquidity below current price, e.g. EQL, obvious low, previous/session low, external swing low |
| `external_liquidity` | Pool at the outer boundary of a major range/dealing range or major swing structure |
| `internal_liquidity` | Pool inside the current range/structure, e.g. minor EQH/EQL or minor swing levels |
| `liquidity_pool` | A validated record with level/zone, side, timeframe, source, and scope |

A pool must be supplied by rule engine/payload. The LLM must not assume all visible highs/lows contain the same liquidity.

### 4.2 Liquidity sources

Examples of sources to label when provided:

```text
EQH / EQL
obvious_high / obvious_low
previous_day_high / previous_day_low
session_high / session_low
range_high / range_low
swing_high / swing_low
external_high / external_low
internal_high / internal_low
```

### 4.3 Sweep, grab, and liquidity run

| Event | Structured meaning |
|---|---|
| `liquidity_grab` | Short, focused penetration/spike through one level, often 1–2 bars; outcome still unknown until reaction confirms |
| `liquidity_sweep` | Broader run through a pool/zone; may end in reversal or continuation |
| `liquidity_run` | Break/close and follow-through in breakout direction; liquidity becomes fuel for continuation |
| `sweep_reversal_candidate` | Sweep followed by return/rejection but MSS/CHoCH not yet confirmed |
| `sweep_reversal_confirmed` | Sweep + opposite displacement + validated MSS/CHoCH, subject to higher-context review |
| `sweep_continuation_confirmed` | Break/close beyond pool + follow-through/BOS + retest context; no valid opposing MSS |

The words `sweep` and `grab` may be used closely, but the payload must distinguish whether reaction/follow-through happened.

### 4.4 Structure: MSS, CHoCH, and BOS

| Term | Meaning in this skill |
|---|---|
| `MSS` / `CHoCH` | Early directional change: confirmed break of relevant opposing structure with displacement when available |
| `BOS` | Confirmed break in the direction of the established/new structure; often continuation confirmation |
| `internal` | Minor/fractal swing structure inside a larger context |
| `external` | Major swing structure that defines broader bias |

A wick alone is not a confirmed MSS/CHoCH/BOS unless rule engine explicitly says so. A valid event should include reference swing, close confirmation, direction, scope, and ideally displacement state.

### 4.5 Fair Value Gap / FVG

FVG is a structured three-candle imbalance zone, not a mandatory future price target.

| State | Meaning |
|---|---|
| `fresh` | Formed and not yet materially revisited according to rule engine |
| `partial_fill` | Price revisited only part of FVG |
| `full_fill` | Price revisited full defined FVG zone |
| `running` | Price moved away without a near-term fill; not a promise of later fill |
| `invalidated` | Rule-engine-defined break/condition makes the FVG no longer valid for the scenario |

### 4.6 Order Block / OB

A valid OB is not simply every last opposite candle. It must be identified by the rule engine using evidence such as:

1. A relevant liquidity event or structured context, when available.
2. Clear displacement away from the origin.
3. BOS/MSS or another validated structure event after departure.
4. Defined zone boundaries.
5. Fresh/mitigated/broken status.

If these fields are absent, call it `possible_origin_candle` or list missing data; do not claim a valid OB.

## 5. Multi-Timeframe Framework

| Layer | Timeframes | ICT/SMC role |
|---|---|---|
| Macro context | W1, D1, H4, H1, M30 | External structure, major liquidity, external OB/FVG, dealing range context |
| Main analysis | M15, M5, M3, M1 | Internal liquidity, local sweep, MSS/BOS, FVG/OB reaction |
| Execution confirmation | M3, M1, 30S | Fine confirmation only; 30S cannot establish independent bias |

Rules:

- Higher timeframe provides map/bias and major external pools when available.
- Lower timeframe provides reaction and timing.
- 30S can confirm a reaction only after M1/M3/M5 context is established.
- Internal MSS against external structure is not automatically a major reversal.
- Countertrend reversal requires a stronger chain: meaningful external/HTF location + sweep + opposite displacement + validated MSS/CHoCH + structural invalidation.

## 6. Stage 1 — Liquidity Mapping

### 6.1 Required liquidity pool fields

A pool should include:

```json
{
  "pool_id": "string",
  "side": "buy_side|sell_side",
  "scope": "internal|external",
  "source": "eqh|eql|obvious_high|obvious_low|previous_day_high|previous_day_low|session_high|session_low|range_high|range_low|swing_high|swing_low|unknown",
  "timeframe": "M15",
  "low": 0,
  "high": 0,
  "status": "resting|touched|swept|broken|unknown",
  "touch_count": 0
}
```

Without pool boundaries, source, side, and scope, do not label a level as structured liquidity.

### 6.2 Liquidity map procedure

1. Read higher-timeframe external pools if supplied.
2. Read current/internal pools around price.
3. Identify nearest BSL and SSL; report distance only if supplied/calculated.
4. Identify whether price is approaching, touching, sweeping, or already beyond the pool.
5. Do not infer direction merely from the existence of a pool.

### 6.3 Draw-on-liquidity rule

Liquidity can act as a possible target/draw, but never state that price **will** take it.

Correct language:

```text
Nearest external BSL is above price and may act as an upside liquidity target.
```

Forbidden language:

```text
Price must take BSL before reversing.
```

## 7. Stage 2 — Sweep and Outcome Classification

### 7.1 Reversal after sweep

A sweep can support `REVERSAL_REVIEW` only when structured evidence shows:

```text
Relevant liquidity pool
→ price breaches/sweeps the pool
→ rejection or opposite displacement
→ confirmed internal MSS/CHoCH
→ retest/FVG/OB context or other timing evidence
```

For countertrend reversal, add:

```text
Meaningful external/HTF location
+ clear structural invalidation reference
+ risk/reward passes independent risk layer
```

### 7.2 Continuation after sweep

A sweep can support `CONTINUATION_REVIEW` only when structured evidence shows:

```text
Liquidity pool breached
→ confirmed close beyond pool
→ displacement/follow-through in same direction
→ BOS or maintained structure
→ retest of FVG/OB/level in trend direction
→ no valid opposing MSS
```

### 7.3 Outcome unknown

If price only touched/breached a pool and no confirmed reaction or follow-through exists:

```text
status = WAIT or WATCH
```

Do not guess reversal versus continuation.

## 8. Stage 3 — MSS / CHoCH and BOS

### 8.1 MSS/CHoCH validation

For a valid MSS/CHoCH, payload should provide:

- Prior structure direction.
- Reference swing level and timeframe.
- Break direction.
- Confirmed close state.
- Scope: internal or external.
- Displacement/reaction state when available.

Interpretation:

```text
Internal MSS
= early/local order-flow shift; useful for LTF timing but not a macro reversal alone.

External MSS
= break of major swing context; stronger bias-shift evidence.
```

### 8.2 BOS validation

For a valid BOS, payload should provide:

- Reference swing.
- Confirmed close beyond the reference.
- Direction.
- Scope.
- Follow-through/displacement if available.

BOS supports continuation or confirms a new structure after MSS. It is not a standalone entry.

### 8.3 Structure conflict

Report conflict when:

- Internal bullish MSS occurs inside a still-valid external bearish structure.
- Internal bearish MSS occurs inside a still-valid external bullish structure.
- Sweep occurred but no confirmed MSS/BOS outcome exists.
- Break was wick-only or unconfirmed.

Use `WAIT`, `WATCH`, or `COUNTERTREND_REVIEW` rather than forcing a directional conclusion.

## 9. Stage 4 — FVG / Imbalance

### 9.1 FVG requirements

A FVG record should include:

```json
{
  "fvg_id": "string",
  "direction": "bullish|bearish",
  "timeframe": "M5",
  "low": 0,
  "high": 0,
  "origin": "displacement|bos|mss|unknown",
  "status": "fresh|partial_fill|full_fill|running|invalidated|unknown",
  "fill_pct": null,
  "scope": "internal|external",
  "parent_structure_event": "string|null"
}
```

### 9.2 FVG rules

- A FVG is a location/context, not a guaranteed fill.
- Fresh FVG aligned with displacement/BOS can support a continuation/retest narrative.
- Partial fill can be sufficient for continuation if price action/structure supports it; no universal fill percentage is assumed.
- Full fill does not automatically invalidate trend or reverse direction.
- Running FVG means unfilled at present; it is not a prediction of future return.
- FVG counter to higher structure is a conflict, not automatic reversal.

### 9.3 FVG and BBMA / Price Action

Use FVG as location:

```text
ICT/SMC: identifies FVG and structure context.
Supply-Demand/Price Action: evaluates reaction at FVG.
BBMA: evaluates whether Reentry timing is mature.
Ichimoku: evaluates trend/regime support or conflict.
```

## 10. Stage 5 — Order Block

### 10.1 OB requirements

A validated OB record should contain:

```json
{
  "ob_id": "string",
  "direction": "bullish|bearish",
  "timeframe": "M5",
  "low": 0,
  "high": 0,
  "origin_type": "last_opposite_candle|base|unknown",
  "liquidity_context": "sweep|none|unknown",
  "displacement": "bullish|bearish|none|unknown",
  "structure_event": "BOS|MSS|CHOCH|none|unknown",
  "freshness": "fresh|mitigated|broken|unknown",
  "touch_count": 0,
  "scope": "internal|external"
}
```

### 10.2 OB validation rules

An OB gains quality when:

- It is associated with a relevant liquidity/sweep context.
- Departure shows displacement.
- Departure leads to validated BOS/MSS/CHoCH.
- Boundaries are known.
- Zone is fresh or mitigation status is known.
- Retest shows structured reaction when used for review.

An OB loses quality when:

- It is only an arbitrary last opposite candle.
- No displacement or structure evidence exists.
- It has been repeatedly mitigated with weakening response.
- It is broken by confirmed far-boundary close/rule-engine invalidation.

### 10.3 OB and reversal/continuation

```text
Continuation:
Trend/structure valid → retest aligned OB → reaction/structure confirmation → BBMA timing review.

Reversal:
Sweep at meaningful liquidity/HTF location → opposite displacement + MSS → retest OB/FVG → strict countertrend review if external bias still opposes.
```

No OB is an entry by itself.

## 11. Premium / Discount and Session Context

These are optional contextual fields in v0.1.0, not entry triggers.

### 11.1 Premium / discount

If a validated dealing range and equilibrium are supplied:

- `premium`: upper half of range; bearish PD arrays may be more relevant in bearish context.
- `discount`: lower half of range; bullish PD arrays may be more relevant in bullish context.
- `equilibrium`: middle of range; often lower-quality location unless structure supports a breakout/retest.

Do not calculate a dealing range from an unclear screenshot. Use only supplied range boundaries.

### 11.2 Session context

Session can be logged as Asia, London, New York, overlap, or off-session. Session is context only in this version.

- Do not hard-code New York kill-zone times into the skill without timezone/DST-aware rule-engine handling.
- Do not call a move “Judas Swing” in v0.1.0; log it as `possible_session_sweep` only if timestamp/session and sweep evidence exist.

## 12. Confluence and Conflict Rules

### 12.1 Core ICT/SMC evidence

Core evidence is strongest when all available facts align:

1. Meaningful liquidity pool or external POI.
2. Structured sweep/break reaction classified as reversal or continuation.
3. Validated MSS/CHoCH or BOS with scope.
4. FVG/OB location aligned with the structure outcome.
5. Known structural invalidation level.

### 12.2 Supporting evidence

These may strengthen but do not replace core ICT/SMC evidence:

- Supply/Demand zone reaction.
- Price-action rejection/engulfing/follow-through.
- BBMA Reentry/CSAK timing.
- Ichimoku regime alignment.
- Volume confirmation if reliable and structured.
- Session context.

### 12.3 Conflicts to report

- Liquidity pool exists but no reaction/outcome after sweep.
- Sweep is reversal candidate but price closes/follows through in sweep direction.
- Internal MSS conflicts with external structure.
- FVG/OB direction conflicts with structure.
- OB/FVG is mitigated repeatedly or broken.
- Proposed direction has no structural invalidation reference.
- 30S-only evidence attempts to define major liquidity/structure.

Never hide conflict to make a setup sound better.

## 13. Analysis Procedure

Evaluate sequentially. Stop at first critical failure.

1. Validate data quality, confirmed candle, timestamps, and required structured blocks.
2. Map external and internal liquidity pools.
3. Identify closest relevant BSL/SSL and current relation to pools.
4. Determine whether event is untouched, touched, sweep/grab, liquidity run, or unknown.
5. Classify outcome: reversal candidate, reversal confirmed, continuation candidate, continuation confirmed, or unresolved.
6. Validate MSS/CHoCH/BOS and internal/external scope.
7. Evaluate FVG records and OB records only if structured and valid.
8. Compare ICT/SMC context with Supply-Demand/Price Action, BBMA, Ichimoku, and risk context.
9. Determine status and list conflicts/missing data.
10. Return journal seed for later outcome review.

## 14. Output Contract

Return valid JSON only. Do not wrap JSON in Markdown fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "skill": "ict-smc-playbook",
  "status": "NO_TRADE|WAIT|WATCH|LIQUIDITY_REVIEW|CONTINUATION_REVIEW|REVERSAL_REVIEW|COUNTERTREND_REVIEW|INVALIDATED",
  "symbol": "string",
  "timeframe_context": {
    "macro_bias": "bullish|bearish|neutral|unknown",
    "analysis_timeframe": "string|null",
    "execution_timeframe": "string|null",
    "structure_alignment": "aligned|countertrend|mixed|unknown"
  },
  "liquidity": {
    "nearest_bsl": {
      "pool_id": "string|null",
      "scope": "internal|external|unknown",
      "source": "string|null",
      "low": null,
      "high": null,
      "status": "resting|touched|swept|broken|unknown"
    },
    "nearest_ssl": {
      "pool_id": "string|null",
      "scope": "internal|external|unknown",
      "source": "string|null",
      "low": null,
      "high": null,
      "status": "resting|touched|swept|broken|unknown"
    },
    "event": "none|liquidity_grab|liquidity_sweep|liquidity_run|unknown",
    "outcome": "unresolved|reversal_candidate|reversal_confirmed|continuation_candidate|continuation_confirmed|unknown"
  },
  "structure": {
    "prior_bias": "bullish|bearish|neutral|unknown",
    "event": "MSS_BULLISH|MSS_BEARISH|CHOCH_BULLISH|CHOCH_BEARISH|BOS_BULLISH|BOS_BEARISH|NONE|UNKNOWN",
    "scope": "internal|external|none|unknown",
    "confirmed_close": false,
    "displacement": "bullish|bearish|none|unknown"
  },
  "fvg": {
    "exists": false,
    "id": "string|null",
    "direction": "bullish|bearish|null",
    "scope": "internal|external|unknown",
    "low": null,
    "high": null,
    "status": "fresh|partial_fill|full_fill|running|invalidated|unknown"
  },
  "order_block": {
    "exists": false,
    "id": "string|null",
    "direction": "bullish|bearish|null",
    "scope": "internal|external|unknown",
    "low": null,
    "high": null,
    "freshness": "fresh|mitigated|broken|unknown",
    "quality_context": ["string"]
  },
  "confluence": {
    "core_support": ["string"],
    "supporting": ["string"],
    "conflicts": ["string"]
  },
  "risk_structure": {
    "invalidation_reference": null,
    "invalidation_basis": "external_ob|external_fvg|external_swing|liquidity_sweep_extreme|missing",
    "note": "ICT/SMC provides structure context; final SL/R:R is checked by the risk layer."
  },
  "missing_data": ["string"],
  "manual_review_checklist": ["string"],
  "journal_seed": {
    "liquidity_event": "string|null",
    "structure_event": "string|null",
    "fvg_state": "string|null",
    "ob_state": "string|null",
    "technical_lesson_candidate": "string|null"
  }
}
```

## 15. Paper Journal and Learning Rules

For each analyzed ICT/SMC event, record when available:

- Event ID, timestamp UTC, symbol, session, and timeframe stack.
- External and internal liquidity pools with source/scope/status.
- Whether event became a grab, sweep, run, reversal, continuation, or remained unresolved.
- MSS/CHoCH/BOS event, scope, reference swing, and displacement state.
- FVG direction, scope, fill status, and relation to structure.
- OB direction, freshness, touch count, and relation to structure.
- Supply-Demand/Price Action, BBMA, and Ichimoku confluence states.
- Structural invalidation reference.
- Final decision-support status and outcome.
- Technical lesson and rule-change candidate.

The agent may propose hypotheses only after a sufficient sample. It may not change definitions or parameters automatically.

```text
Correct learning loop:
Collect structured events/outcomes
→ compare sweep reversal vs sweep continuation
→ compare internal vs external MSS quality
→ compare fresh vs mitigated FVG/OB reactions
→ identify a hypothesis
→ user approval
→ backtest on new sample
→ compare with old rule
→ only then revise skill/rule engine version
```

## 16. Common Mistakes to Avoid

- Calling every high/low a liquidity pool.
- Assuming price must take a nearby liquidity pool.
- Treating every sweep as reversal.
- Treating every breakout through liquidity as continuation without follow-through.
- Calling a wick-only break a confirmed MSS/BOS.
- Upgrading internal MSS to major trend reversal without external context.
- Treating every three-candle gap as tradeable FVG without displacement/structure context.
- Assuming every FVG must be filled.
- Calling every last opposite candle an OB.
- Using FVG/OB alone as an entry reason.
- Hard-coding kill-zone time rules without UTC/DST-aware data.
- Letting ICT/SMC narrative override Data Quality, Rule Engine, risk gate, or human review.
