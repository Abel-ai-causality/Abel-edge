# Math Audit 06: Rank Metrics

## Principle

The repo's rank family is meant to answer a different question from Sharpe-family
metrics: are position sizes aligned with realized outcomes, rather than merely
producing a good aggregate PnL path?

## Concrete Algorithms

1. IC applicability in `causal_edge/validation/metrics.py:145-150`
2. `_compute_ic()` in `causal_edge/validation/metrics.py:355-383`
3. Conditional IC gates in `causal_edge/validation/metrics.py:228-233`

## Current Implementation

The IC family activates only when `positions` is present and aligned with `pnl`.

The helper then:

1. Filters to `abs(position) > 0.01`
2. Computes `ic = spearmanr(active_positions, active_pnl)`
3. Computes `ic_hit_rate = mean(sign(position) == sign(pnl))`
4. Computes monthly IC values and reports:
   - `ic_stability = fraction(monthly_ic > 0)`
   - `ic_monthly_mean = mean(monthly_ic)`

## What This Metric Really Is

This is a time-series exposure-vs-realized-PnL rank correlation. It is not the more
common cross-sectional IC used in stock-selection frameworks.

## Current Concerns

1. The project uses the term "IC" without always clarifying that this is a time-series
   Spearman correlation, not a cross-sectional IC.
2. `ic_hit_rate` becomes weak for long-only strategies because active positions are
   often always positive, making the metric close to a win-rate proxy.
3. The `0.01` active threshold is a policy choice, not a mathematical identity.

## Audit Questions

1. Should the public wording say "time-series IC" explicitly?
2. Should `ic_hit_rate` remain in the payload if it adds little information for
   long-only strategies?
3. Is Spearman on `position` vs `pnl` the right rank metric for this framework's goals?
