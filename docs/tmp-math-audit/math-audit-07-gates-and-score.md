# Math Audit 07: Gates And Score Semantics

## Principle

Metrics do not matter until the system turns them into decisions. This document covers
the exact decision layer that produces PASS, FAIL, KEEP, and DISCARD.

## Concrete Algorithms

1. `validate()` in `causal_edge/validation/metrics.py:192-234`
2. `validate_strategy()` in `causal_edge/validation/gate.py:27-100`
3. `_count_total()` in `causal_edge/validation/gate.py:178-184`
4. `decide_keep_discard()` in `causal_edge/validation/metrics.py:237-271`

## Current Implementation

### PASS/FAIL gate

The live gate applies these checks:

- `T6 DSR`
- `T13 DrawdownTime`
- `T13 MaxDDDuration`
- `T14 LossYrs`
- `T15 Lo`
- `T15 Omega`
- `T15 MaxDD`
- `Return floor`
- `Sharpe/Lo`
- conditional `PositionIC`
- conditional `PositionIC stab`

The removed validation families are not part of the live gate:

- `T7 PBO`
- `T12 OOS/IS`
- `T13 NegRoll`
- `Bootstrap p` as a gate

### Score denominator

`_count_total()` sets:

- base count `7`
- plus `1` if `omega_applicable` is true
- plus `1` if `loss_years_applicable` is true
- plus `1` if `position_ic_applicable` is true
- plus `1` if `position_ic_stability_applicable` is true

So the live denominator is conditional, commonly `7` through `11`, with `PositionIC` and `PositionIC stab` counted separately rather than as one bundled `+2` rule.

This denominator is the only active score contract. Legacy fixed-denominator narratives
such as `15/15`, `15/21`, or `20/21` are historical migration context, not live math.

### KEEP/DISCARD

`decide_keep_discard()` uses:

1. one optimize metric that must improve
2. guardrail metrics that must not degrade past tolerance
3. an absolute drawdown veto using the same `validation.max_dd` policy key as PASS/FAIL

This is a product comparator, not a significance test.

## Current Concerns

1. The OOS/IS gate has been removed from the live contract because half-split Sharpe
   could not support a defensible IS/OOS claim without explicit split provenance.
2. The gate set mixes mathematically different objects: some are path diagnostics,
   some are anti-gaming heuristics, and some are statistical confidence proxies.
3. `KEEP` or `DISCARD` may be interpreted as scientific truth even though the function
   is a policy layer over selected metrics.

## Audit Questions

1. Which rules are mathematical necessities and which are product policy?
2. Should the score be presented as a checklist count at all, or only as named failures?
3. Should `KEEP` and `DISCARD` be documented explicitly as policy outputs rather than
   statistical conclusions?
