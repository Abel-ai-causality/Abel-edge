# Math Audit 09: Walk-Forward ML

## Principle

This example tries to show a more complex signal generation flow without violating
the same no-look-ahead contract as the simple strategies.

## Concrete Algorithms

1. `MomentumMLEngine.compute_signals()` in `examples/momentum_ml/engine.py:27-91`
2. `_rsi()` in `examples/momentum_ml/engine.py:103-109`

## Current Implementation

### Features

The engine builds these shifted features from synthetic returns:

- `ret_1d = return[t-1]`
- `ret_5d = sum(return[t-5:t-1])`
- `ret_20d = sum(return[t-20:t-1])`
- `vol_20d = std(return[t-20:t-1])`
- `rsi_14 = RSI(return history through t-1)`

All features use `.shift(1)` before being used for prediction.

### Target and training loop

The target is same-index next-step direction relative to the shifted features:

```python
target[t] = 1 if return[t] > 0 else 0
```

The model trains on a rolling 126-day window, retrains every 5 days, and goes long
only when predicted `P(up) > 0.55`.

### RSI helper

The helper computes a simple rolling RSI from average gains and losses:

```python
delta = diff(series)
gain = rolling_mean(max(delta, 0))
loss = rolling_mean(max(-delta, 0))
rs = gain / loss
rsi = 100 - 100 / (1 + rs)
```

## Current Concerns

1. `_rsi()` is the simple rolling-average version, not Wilder's smoothed RSI.
2. The example uses synthetic autocorrelated returns, so model success here should not
   be read as evidence of production predictive power.
3. The threshold `0.55` is a policy choice, not a mathematically derived optimum.

## Audit Questions

1. Is the feature-target alignment correct enough to certify zero look-ahead?
2. Should the docs call out that this is a pedagogical walk-forward loop, not an
   audited production ML pipeline?
3. Does the repo want to standardize on Wilder RSI terminology or keep the simpler form?
