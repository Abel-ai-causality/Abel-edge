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
sharpe = mean(pnl) / std(pnl, ddof=1) * sqrt(periods_per_year)
```

The active profile now supplies `periods_per_year`, so annualization is no longer
hard-coded to `252` for every profile.

### Sortino

```python
downside = pnl[pnl < 0]
sortino = mean(pnl) / std(downside, ddof=1) * sqrt(periods_per_year)
```

If there are fewer than two downside observations, the implementation returns `0.0`.
Sortino annualization now follows the same profile `periods_per_year` contract as Sharpe.

### Lo-adjusted Sharpe

The code now applies a simplified lag-1 serial-correlation penalty:

```python
cf = 1 + 2 * rho_1 * (1 - 1 / periods_per_year)
lo_adjusted = sharpe * sqrt(1 / cf)
```

The implementation is now a profile-aware, one-lag approximation rather than a
fixed-252, ten-lag truncation.

### Deflated Sharpe Ratio

The code computes a DSR-style probability using:

- sample size `T`
- search-space size `K`
- annualized Sharpe estimate using profile `periods_per_year`
- skew
- raw kurtosis from `scipy.stats.kurtosis(..., fisher=False)`

The runtime now accepts an optional externally declared `dsr_trials` count. When the
caller does not provide it, the active profile supplies the fallback default through
`validation.dsr_K`.

## Current Concerns

1. `sortino = 0.0` when there is no downside is a deterministic sentinel, not a
   mathematically natural limit.
2. `lo_adjusted` is now explicitly a simplified one-lag penalty, not a full
   long-horizon autocorrelation adjustment.
3. `_dsr()` now explicitly uses raw kurtosis to match the intended DSR variance
   convention. Any future formula changes must preserve that contract or version it.
4. The validator cannot independently verify whether an externally declared
   `dsr_trials` count is truthful; the gate depends on operator-supplied research metadata.
5. The doc claim is stronger than the implementation if the project presents Lo or
   DSR as canonical rather than pragmatic approximations.

## Audit Questions

1. Is Lo-adjusted Sharpe intended as a literature-faithful estimator or as a stable
   anti-persistence penalty?
2. Is DSR trustworthy enough to remain a live gate, or should it be diagnostic only?
3. Should the runtime eventually require explicit `dsr_trials` metadata for promoted
   strategies instead of allowing the profile fallback?
4. Should HFT continue to share `periods_per_year=252`, or should intraday profiles
   eventually use a different annualization contract?
