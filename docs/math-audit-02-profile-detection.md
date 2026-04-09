# Math Audit 02: Profile Detection

## Principle

Validation thresholds depend on the selected profile. The profile selector is
therefore part of the math contract, not a convenience feature.

## Concrete Algorithm

`detect_profile()` in `causal_edge/validation/metrics.py:47-57`

## Current Implementation

The selector uses two rules:

```python
if median_timestamp_gap < 1 hour:
    return "hft"

ann_vol = std(pnl, ddof=1) * sqrt(252)
if ann_vol > 0.60:
    return "crypto_daily"

return "equity_daily"
```

## What The Algorithm Is Doing

1. It first infers whether the series is intraday from timestamp spacing.
2. If not intraday, it uses annualized PnL volatility to classify the series as
   crypto-like or equity-like.

## Current Concerns

1. The classification input is strategy `pnl`, not underlying asset returns.
2. Because `pnl` depends on position sizing, the detector is not leverage-invariant.
3. The threshold `0.60` is a product rule, not a mathematical identity.
4. A strategy that changes only its sizing may flip profile and therefore flip the
   gate set applied to it.

## Audit Questions

1. Should profile detection operate on strategy PnL at all?
2. Should profile be explicit user config instead of inferred when correctness matters?
3. If inference remains, should it use underlying return volatility rather than PnL volatility?
