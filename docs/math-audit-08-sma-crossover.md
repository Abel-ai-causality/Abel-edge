# Math Audit 08: SMA Crossover

## Principle

Trend following via moving-average crossover is the simplest signal-generation rule
in the repo. It is useful as the cleanest audit example of a lagged indicator.

## Concrete Algorithm

`SMAEngine.compute_signals()` in `examples/sma_crossover/engine.py:20-32`

## Current Implementation

The example generates synthetic prices, then computes:

```python
fast_ma = rolling_mean(prices, 10).shift(1)
slow_ma = rolling_mean(prices, 30).shift(1)
position = 1.0 if fast_ma > slow_ma else 0.0
positions[: slow + 1] = 0.0
```

## Why It Matters

This engine is the cleanest example of the repo's no-look-ahead contract:

- the signal is simple
- the lagging rule is explicit
- the warm-up period is explicit

## Current Concerns

1. The example uses synthetic prices, so it is not a test of live market behavior.
2. The signal is binary long/flat only, so it does not exercise sizing logic.

## Audit Questions

1. Is the warm-up rule `slow + 1` exactly the intended causal boundary?
2. Should the example remain synthetic, or should the repo include a real-data
   crossover example to demonstrate the same principle on actual bars?
