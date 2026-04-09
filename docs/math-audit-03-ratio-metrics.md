# Math Audit 03: Ratio Metrics

## Principle

The repo's ratio family tries to measure return quality relative to dispersion,
while discounting serial-correlation gaming and multiple-testing effects.

## Concrete Algorithms

1. `sharpe` in `causal_edge/validation/metrics.py:92`
2. `sortino` in `causal_edge/validation/metrics.py:93`, helper at `284-289`
3. `lo_adjusted` in `causal_edge/validation/metrics.py:98-102`
4. `dsr` in `causal_edge/validation/metrics.py:105`, helper at `292-305`

## Current Implementation

### Sharpe

```python
sharpe = mean(pnl) / std(pnl, ddof=1) * sqrt(252)
```

### Sortino

```python
downside = pnl[pnl < 0]
sortino = mean(pnl) / std(downside, ddof=1) * sqrt(252)
```

If there are fewer than two downside observations, the implementation returns `0.0`.

### Lo-adjusted Sharpe

The code computes lag-1 through lag-10 autocorrelations, then applies a correction:

```python
cf = 1 + 2 * sum(rho_k * (1 - k / 252))
lo_adjusted = sharpe * sqrt(1 / cf)
```

The implementation is a finite-lag, fixed-252 approximation.

### Deflated Sharpe Ratio

The code computes a DSR-style probability using:

- sample size `T`
- search-space size `K`
- daily Sharpe estimate
- skew
- kurtosis-like term from `scipy.stats.kurtosis`

The active profile supplies `K` through `validation.dsr_K`.

## Current Concerns

1. `sortino = 0.0` when there is no downside is a deterministic sentinel, not a
   mathematically natural limit.
2. `lo_adjusted` uses a fixed 10-lag window and hard-coded `252`, which may be good
   enough as a penalty but is still a modeling choice.
3. `_dsr()` uses `scipy.stats.kurtosis()`, which returns excess kurtosis by default;
   the formula should be checked against the intended paper notation.
4. The doc claim is stronger than the implementation if the project presents Lo or
   DSR as canonical rather than pragmatic approximations.

## Audit Questions

1. Is Lo-adjusted Sharpe intended as a literature-faithful estimator or as a stable
   anti-persistence penalty?
2. Is DSR trustworthy enough to remain a live gate, or should it be diagnostic only?
3. Should the annualization constant be profile-dependent rather than fixed at `252`?
