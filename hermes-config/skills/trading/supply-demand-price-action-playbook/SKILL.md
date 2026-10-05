---
name: supply-demand-price-action-playbook
description: Analyze structured TradingView and rule-engine payloads using Supply-Demand, Price Action, Market Structure, OB/FVG, sweep, BOS/CHoCH, and multi-timeframe context. This skill identifies trade location and structural validity for paper-only decision support; it never executes broker actions.
version: 0.1.0
metadata:
  hermes:
    tags: [trading, supply-demand, price-action, market-structure, bos, choch, order-block, fvg, xauusd, paper-trading]
    category: trading
---

# Supply-Demand & Price Action Decision-Support Playbook v0.1.0

## 0. Purpose, Scope, and Non-Negotiable Rules

This skill converts the user's Supply-Demand and Price Action curriculum into a structured analysis layer for the trading agent. Its main job is to answer:

```text
1. Is price currently at a meaningful trade location?
2. Is the zone fresh, mitigated, broken, or structurally unclear?
3. Is there valid price-action and market-structure confirmation?
4. What invalidates the setup?
5. Should the system return NO_TRADE, WAIT, WATCH, ENTRY_REVIEW,
   COUNTERTREND_REVIEW, or INVALIDATED?
```

```text
CURRENT MODE: ANALYSIS + PAPER JOURNAL ONLY
BROKER EXECUTION: FORBIDDEN
HUMAN REVIEW: REQUIRED
```

The agent may identify structured confluence and prepare a review. It must never:

- Open, close, reverse, modify, or cancel any broker position.
- Treat a supply/demand zone, OB, FVG, candle pattern, BOS, or CHoCH as a guaranteed trade.
- Invent zones, price levels, candle patterns, volume conditions, BOS/CHoCH, or market history that are not present in the validated payload.
- Read precise coordinates from a screenshot as facts.
- Override a data-quality failure, risk gate, or a `NO_TRADE` decision from the rule engine.
- Change strategy rules, zone definitions, Pine Script, or risk limits automatically.

All factual price, zone, structure, volume, and timeframe claims must be grounded in the validated payload or rule-engine output. Screenshots are optional visual context only.

## 1. Role in the Multi-Skill System

This skill is not the final trading decision-maker. Its responsibility is **trade location + structural validity**.

| Framework | Primary role |
|---|---|
| Supply-Demand & Price Action | Trade location, zone freshness, reaction, candle confirmation, structure validity |
| BBMA | Timing cycle: Extreme, MHV, CSAK, Reentry, CSM |
| ICT/SMC | Liquidity map, internal/external liquidity, MSS, FVG, OB, session context |
| Ichimoku | Trend/regime and momentum filter |
| Rule/Risk engine | Data quality, cooldown, R:R, risk limits, no-trade and halt decisions |
| Confluence Orchestrator | Combines support/conflict from the skills; produces final review status |

This skill may return a location/structure assessment. The orchestrator must combine it with BBMA, ICT/SMC, Ichimoku, and risk results before a final `ENTRY_REVIEW` is emitted.

## 2. Source Hierarchy and Missing-Data Rules

Use source priority in this order:

1. Validated TradingView/rule-engine payload.
2. Structured multi-timeframe snapshot.
3. Structured supply/demand zones, OB/FVG, swings, BOS/CHoCH, sweep, volume, and candle-pattern fields.
4. Journal/position context, if available.
5. Screenshot only as non-numeric supplementary context.

If a required fact is absent, list it in `missing_data`. Do not infer it from a single candle or vague chart description.

Examples:

```text
No zone boundaries in payload → do not invent a supply/demand zone.
No prior swing reference → do not claim a BOS or CHoCH is valid.
No zone touch/mitigation history → do not label a zone fresh or mitigated.
No closed candle → do not confirm engulfing, rejection, BOS, or CHoCH.
No volume data → state volume confirmation unavailable; do not claim volume spike.
```

## 3. Status Vocabulary

Use only these status values at this skill layer:

| Status | Meaning |
|---|---|
| `NO_TRADE` | Data invalid, no trade location, zone broken/exhausted, risk reference missing, or setup contradicts core structure |
| `WAIT` | Location may be relevant, but candle/structure/zone confirmation is incomplete |
| `WATCH` | Zone or structure is developing; observe reaction without entry review |
| `LOCATION_REVIEW` | A meaningful zone/location is present, but timing belongs to BBMA/other skills |
| `ENTRY_REVIEW` | Fresh/relevant location + valid structure + price-action confirmation + clear invalidation are present; requires human/risk/orchestrator review |
| `COUNTERTREND_REVIEW` | Valid location and reversal evidence oppose higher context; stricter evidence required |
| `INVALIDATED` | Previously valid location/setup is structurally broken or invalidated |

These are not broker commands and do not guarantee outcome.

## 4. Objective Vocabulary

This skill uses the following terms only when payload/rule engine provides the underlying facts.

### 4.1 Market regime

| Regime | Minimum structured description |
|---|---|
| `bullish_trend` | Validated sequence/context of HH/HL or bullish external structure |
| `bearish_trend` | Validated sequence/context of LL/LH or bearish external structure |
| `range` | Defined upper/lower range boundary with no confirmed directional structure |
| `transition` | Structure conflict, CHoCH/MSS pending, or breakout/retest not yet confirmed |
| `unknown` | Insufficient data |

### 4.2 Swing and structure

- **Swing high / swing low**: a validated local turning point from the rule engine.
- **BOS**: a confirmed candle close beyond a relevant swing in the prevailing direction. A wick alone is not sufficient.
- **CHoCH / MSS**: a confirmed break of relevant opposing structure suggesting a change in character; it is an early shift, not an entry by itself.
- **Internal structure**: minor/fractal swings inside a larger range or trend.
- **External structure**: major swing structure that defines broader context.

### 4.3 Price action

Use pattern names only when supplied by a deterministic detector or explicitly structured payload:

- `bullish_engulfing`
- `bearish_engulfing`
- `bullish_pin_bar`
- `bearish_pin_bar`
- `hammer`
- `shooting_star`
- `inside_bar`
- `rejection`
- `none`
- `unknown`

A candle pattern is meaningful only at a relevant location. A bullish engulfing in the middle of a range is not sufficient evidence for a buy review.

### 4.4 Supply and demand zones

- **Demand zone**: a defined base/consolidation or validated bullish origin followed by impulsive rally/displacement.
- **Supply zone**: a defined base/consolidation or validated bearish origin followed by impulsive drop/displacement.
- **Fresh / unmitigated**: price has not materially returned to the zone since it formed, according to the rule-engine definition.
- **Mitigated**: price has returned/touched the zone after formation; quality is reduced unless payload/rules classify a valid retest.
- **Broken**: a confirmed structural close through the relevant far boundary according to the zone/rule definition.
- **Refined zone**: a lower-timeframe sub-zone inside a higher-timeframe location. It cannot be used without knowing the parent zone/context.

### 4.5 Order block and FVG boundary

This skill recognizes OB and FVG as supplied structural locations; detailed ICT definitions belong to the ICT/SMC skill.

- **OB**: use only validated `ob_external`, `ob_internal`, or structured zone records.
- **FVG**: use only validated `fvg_external`, `fvg_internal`, or structured zone records.
- **FVG fill** is not guaranteed. A partial fill, full fill, or no fill must come from data/rules; never assume price must fill every FVG.

## 5. Multi-Timeframe Location Framework

### 5.1 Timeframe roles

| Layer | Timeframes | Role in this skill |
|---|---|---|
| Macro context | W1, D1, H4, H1, M30 | Major supply/demand, external structure, high-level POI, major range |
| Main analysis | M15, M5, M3, M1, 30S | Zone reaction, internal structure, price action, refinement |
| Execution confirmation | M3, M1, 30S | Fine confirmation only; not independent directional bias |

### 5.2 Rules

- Higher timeframe maps major zones and broad context when data exists.
- Lower timeframe refines a location and waits for price-action/structure confirmation.
- 30S cannot establish independent trend or zone validity. It may only confirm an already-identified M1/M3/M5 location.
- A lower-timeframe countertrend reaction may be analyzed, but must be flagged `COUNTERTREND_REVIEW` when it opposes available higher context.
- If higher context is unavailable, do not invent it. Use `WAIT`, `WATCH`, or lower quality.

## 6. Supply-Demand Zone Evaluation

### 6.1 Required zone fields

A zone should contain, when available:

```json
{
  "zone_id": "string",
  "type": "demand|supply",
  "timeframe": "M15",
  "low": 0,
  "high": 0,
  "origin_pattern": "DBR|RBD|OB|base|unknown",
  "freshness": "fresh|mitigated|broken|unknown",
  "touch_count": 0,
  "departure": "bullish_impulse|bearish_impulse|weak|unknown",
  "bos_after_departure": "bullish|bearish|none|unknown",
  "volume_context": "spike|normal|low|unavailable",
  "parent_zone_id": null
}
```

If boundaries or status are missing, do not treat the zone as an entry location. Return `WAIT` and list missing fields.

### 6.2 Zone quality assessment

Assess facts, not certainty.

| Feature | Supports quality | Reduces quality |
|---|---|---|
| Departure | Clear impulsive move/displacement | Weak/no clear departure |
| Structure | BOS after departure | No structure confirmation |
| Freshness | Fresh/unmitigated first return | Multiple touches or mitigated repeatedly |
| Location | Aligns with external structure/POI | Middle of range or against major context |
| Reaction | Rejection/engulfing + follow-through | Touch without reaction or failed follow-through |
| Volume | Spike/confirmation if reliable data exists | Volume unavailable is neutral; do not invent it |
| Risk | Clear far boundary/invalidation | No structural invalidation reference |

### 6.3 Zone status rules

```text
Fresh relevant zone + no reaction yet
→ WATCH

Fresh or valid mitigated zone + candle confirmation pending
→ WAIT

Fresh/relevant zone + confirmed reaction + valid structure + clear invalidation
→ LOCATION_REVIEW or ENTRY_REVIEW

Zone broken by confirmed close through far boundary
→ INVALIDATED

Multiple mitigations / unclear zone / no departure / no structural reference
→ NO_TRADE or WAIT
```

## 7. Price-Action Confirmation at a Location

### 7.1 Valid principle

Never enter because price merely touches a zone. Require evidence of reaction.

Evidence can include, if supplied:

- Rejection/pin bar at supply or demand.
- Engulfing candle at a meaningful location.
- Strong displacement away from the zone.
- Break/reclaim of minor structure.
- Retest after breakout.
- Volume spike or volume anomaly, if volume data is reliable and supplied.
- Follow-through on the next confirmed candle.

### 7.2 Reversal sequence

A generic reversal sequence is:

```text
Relevant supply/demand or external POI
→ liquidity sweep or failed breakout if supplied
→ rejection / engulfing / displacement
→ internal CHoCH/MSS
→ retest or refined confirmation
→ review timing through BBMA
```

The presence of a pattern alone is insufficient. The sequence must be grounded in structured payload evidence.

### 7.3 Continuation sequence

A generic continuation sequence is:

```text
Trend or external structure remains valid
→ pullback into demand/supply, OB, FVG, or prior breakout-retest area
→ rejection / price-action defence
→ internal BOS in trend direction
→ BBMA continuation reentry timing
```

### 7.4 False breakout / trap conditions

Flag a potential trap if payload confirms:

- Break beyond a zone/level followed by close back inside.
- Long wick through a key level plus opposite displacement.
- Breakout without follow-through and immediate rejection.
- Sweep of a high/low followed by CHoCH/MSS opposite direction.
- Zone break where body close is not confirmed, only wick penetration.

Do not label a trap merely because price moved against the initial idea. Use only validated structure/candle data.

## 8. BOS, CHoCH, and Structural Confirmation

### 8.1 BOS

A BOS is valid only if payload/rule engine confirms:

1. A reference swing exists.
2. A confirmed candle close breaks the reference swing.
3. The break direction is known.
4. The event is not only a wick/temporary penetration.

BOS can support continuation, but it is not an entry by itself. Check location, retest, and price action.

### 8.2 CHoCH / MSS

A CHoCH/MSS is valid only if payload/rule engine identifies:

1. A prior directional structure exists.
2. Relevant opposing structure is broken with confirmed close.
3. The break is associated with meaningful displacement/price action when available.

CHoCH/MSS is an early change signal. It requires location and follow-through/retest context before entry review.

### 8.3 Internal and external structure

- Internal BOS/CHoCH can be used for lower-timeframe timing.
- External BOS/CHoCH carries more weight for directional context.
- Do not call an internal break a full reversal of higher context without external evidence.
- If internal and external structure conflict, report the conflict and downgrade confidence/status.

## 9. OB, FVG, External Structure, and Invalidation

### 9.1 Structural SL/invalidation hierarchy

Use only values supplied by the rule engine. The hierarchy is:

```text
1. External OB far boundary
2. External FVG far boundary
3. External swing high/low
4. Supply/demand zone far boundary
5. Relevant BBMA Extreme/OB reference
6. ATR buffer if supplied
```

For a buy, invalidation generally lies below the relevant demand/OB/FVG/swing. For a sell, it generally lies above the relevant supply/OB/FVG/swing.

### 9.2 Zone break vs wick

- Wick into or beyond a zone is not automatically invalidation.
- A confirmed close through the far boundary, or another rule-engine-defined break condition, is required to mark `INVALIDATED`.
- If only wick data exists and reaction is unclear, use `WAIT`.

### 9.3 Breaker and mitigation

- A broken demand zone may later act as supply; a broken supply zone may later act as demand only if the rule engine/structured payload identifies the role flip.
- A mitigation/retest can be relevant but should not be assumed strong after multiple touches.
- The skill may label `role_flip_candidate` or `mitigation_review`; it must not invent a breaker block.

## 10. Volume Rules

Volume is supportive, not mandatory, because XAUUSD/CFD feeds may expose tick volume rather than centralized exchange volume.

- If payload identifies a reliable spike/anomaly at a key location, list it as confluence.
- If volume is unavailable, report `volume_confirmation_unavailable`; do not reject solely for this reason.
- A volume spike in the middle of nowhere is not evidence by itself.
- Treat claimed volume/order-flow facts as unavailable unless they are provided by the payload or an appropriate data source.

## 11. Confluence and Conflict Rules

### 11.1 Core evidence

These carry the most weight:

1. Valid trade location: supply, demand, OB, FVG, major swing, or external POI.
2. Zone freshness/status and clear boundaries.
3. Valid market structure: BOS, CHoCH/MSS, or clearly documented trend/range context.
4. Price-action reaction at the location.
5. Structural invalidation and risk reference.

### 11.2 Supporting evidence

These improve quality but cannot replace core evidence:

- BBMA timing state.
- Ichimoku alignment.
- Volume confirmation.
- ADX/DI, MACD, Stoch RSI, VW trend.
- Session/time context.

### 11.3 Conflicts

Report, do not hide:

- Entry direction conflicts with external structure.
- Price is in the middle of a range/no zone.
- Zone is already broken or repeatedly mitigated.
- BBMA timing exists but no valid location.
- Price-action pattern conflicts with trend/structure.
- Ichimoku/other filter materially opposes direction.
- SL/invalidation not available.

Do not add scores blindly. A larger number of indicators does not equal a better setup.

## 12. Analysis Procedure

Evaluate sequentially. Stop at the first critical failure.

1. Validate data quality, confirmed candle, timeframe, and available context.
2. Identify market regime and external/internal structure.
3. Verify whether a structured trade location exists.
4. Assess zone type, boundaries, freshness, mitigation, departure, and BOS after departure.
5. Check liquidity sweep/failed breakout/trap only if structured evidence exists.
6. Check price-action reaction and follow-through at the location.
7. Check BOS/CHoCH/MSS and whether it is internal or external.
8. Determine invalidation/SR reference from OB/FVG/swing/zone.
9. Identify support/conflict from BBMA, Ichimoku, and other indicator blocks.
10. Decide a status for this skill layer.
11. Return facts, interpretations, conflicts, missing data, and manual review checklist.

## 13. Output Contract

Return valid JSON only. Do not wrap JSON in Markdown fences.

```json
{
  "analysis_mode": "PAPER_ONLY",
  "skill": "supply-demand-price-action-playbook",
  "status": "NO_TRADE|WAIT|WATCH|LOCATION_REVIEW|ENTRY_REVIEW|COUNTERTREND_REVIEW|INVALIDATED",
  "symbol": "string",
  "timeframe_context": {
    "macro_regime": "bullish_trend|bearish_trend|range|transition|unknown",
    "analysis_timeframe": "string",
    "execution_timeframe": "string|null",
    "structure_alignment": "aligned|countertrend|mixed|unknown"
  },
  "location": {
    "exists": false,
    "type": "demand|supply|bullish_ob|bearish_ob|bullish_fvg|bearish_fvg|support|resistance|equilibrium|none|unknown",
    "zone_id": "string|null",
    "timeframe": "string|null",
    "low": null,
    "high": null,
    "freshness": "fresh|mitigated|broken|unknown",
    "touch_count": null,
    "parent_location": "string|null"
  },
  "structure": {
    "external_bias": "bullish|bearish|neutral|unknown",
    "internal_bias": "bullish|bearish|neutral|unknown",
    "event": "BOS_BULLISH|BOS_BEARISH|CHOCH_BULLISH|CHOCH_BEARISH|NONE|UNKNOWN",
    "event_scope": "internal|external|none|unknown",
    "sweep_state": "none|buy_side|sell_side|unknown",
    "displacement": "bullish|bearish|none|unknown"
  },
  "price_action": {
    "pattern": "bullish_engulfing|bearish_engulfing|bullish_pin_bar|bearish_pin_bar|hammer|shooting_star|inside_bar|rejection|none|unknown",
    "confirmed": false,
    "follow_through": "bullish|bearish|none|unknown",
    "volume_context": "spike|normal|low|unavailable|unknown"
  },
  "confluence": {
    "core_support": ["string"],
    "supporting": ["string"],
    "conflicts": ["string"]
  },
  "risk_structure": {
    "invalidation_reference": null,
    "invalidation_basis": "external_ob|external_fvg|external_swing|zone_far_boundary|bbma_extreme|atr_buffer|missing",
    "zone_break_state": "not_broken|wick_only|confirmed_break|unknown"
  },
  "missing_data": ["string"],
  "manual_review_checklist": ["string"],
  "journal_seed": {
    "setup_type": "reversal|continuation|breakout_retest|role_flip|none|unknown",
    "zone_status": "fresh|mitigated|broken|unknown",
    "structure_event": "string|null",
    "technical_lesson_candidate": "string|null"
  }
}
```

## 14. Paper Journal and Learning Rules

For every analyzed location, record when available:

- `event_id` / `alert_id`.
- Symbol, session, and timeframe stack.
- Market regime and structure context.
- Zone ID/type/timeframe/boundaries/freshness/touch count.
- Whether the zone was fresh, mitigated, broken, or role-flipped.
- BOS/CHoCH/MSS and internal/external scope.
- Sweep, displacement, candle pattern, and volume context.
- BBMA and Ichimoku confluence states from their separate skills.
- Structural invalidation reference.
- Final status and outcome when known.
- Whether price reacted, swept first, invalidated, reached a target, or remained unclear.
- Technical lesson and rule-change candidate.

The agent may propose a hypothesis only after a meaningful sample is reviewed. It may never change zone definitions, strategy conditions, or rules automatically.

```text
Correct learning loop:
Collect structured examples and outcomes
→ classify successful/failed/unclear location reactions
→ compare fresh vs mitigated zones, internal vs external structure,
  and price-action confirmation types
→ identify a hypothesis
→ user approval
→ backtest the hypothesis on a new sample
→ compare results
→ only then revise rule-engine/skill version
```

## 15. Common Mistakes to Avoid

- Calling every consolidation a supply/demand zone.
- Entering merely because price touches a zone.
- Treating a wick through a zone as a confirmed zone break.
- Calling any small swing break a major BOS/CHoCH.
- Treating all FVGs as mandatory fill targets.
- Calling every last opposite candle an order block.
- Calling a volume spike proof of institutional activity without location/reaction context.
- Using a candle pattern in the middle of a range as an entry reason.
- Ignoring a repeatedly mitigated or structurally broken zone.
- Letting BBMA/Ichimoku indicators override a missing trade location or missing invalidation.
- Treating a countertrend reaction as normal trend continuation.
- Changing rules from one successful or failed example.
