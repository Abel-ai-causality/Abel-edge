# Math Audit 06: Rank Metrics

## Principle

The repo's rank family is meant to answer a different question from Sharpe-family
metrics: are position sizes aligned with realized outcomes, rather than merely
producing a good aggregate PnL path?

## Concrete Algorithms

1. Position-Return IC applicability in `causal_edge/validation/metrics.py`
2. `compute_position_ic()` in `causal_edge/validation/position_ic.py`
3. Conditional PositionIC gates in `causal_edge/validation/metrics.py`

## Current Implementation

The Position-Return IC family activates only when `positions` and `asset_return` are present and aligned.

The live gate treats the family as two separate applicable checks:

- `PositionIC`, active when `position_ic_applicable` is true
- `PositionIC stab`, active when `position_ic_stability_applicable` is true

The helper then:

1. Filters to `abs(position) > 0.01`
2. Computes `position_ic = spearmanr(active_positions, active_asset_returns)`
3. Computes `position_hit_rate = mean(sign(position) == sign(asset_return))` on nonzero-return active bars
4. Computes monthly IC values and reports:
   - `position_ic_stability = fraction(monthly_ic > 0)` when enough active months exist
   - `position_ic_monthly_mean = mean(monthly_ic)`

## What This Metric Really Is

This is a time-series position-vs-asset-return rank correlation. It is not the more
common cross-sectional IC used in stock-selection frameworks.

## Current Concerns

1. The project should call this a Position-Return IC, not a generic IC.
2. `position_hit_rate` is a useful diagnostic but should remain non-gating.
3. The `0.01` active threshold is a policy choice, not a mathematical identity.
4. When active inputs are present but position or asset-return variance collapses, the
   live contract now treats PositionIC as applicable with `position_ic = 0.0` rather
   than silently skipping the family.

## Audit Questions

1. Should the public wording use "Position-Return IC" consistently?
2. Should `position_hit_rate` remain in the payload if it stays diagnostic-only?
3. Is Spearman on `position` vs `asset_return` the right rank metric for this framework's goals?
