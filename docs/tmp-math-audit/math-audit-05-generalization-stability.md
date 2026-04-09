# Math Audit 05: Generalization And Stability

## Principle

A strategy should not only look good in aggregate. It should survive out-of-sample,
across time slices, and under alternative path splits.

## Concrete Algorithms

1. Removed `oos_is` family audit record from `causal_edge/validation/metrics.py`
2. `loss_years` in `causal_edge/validation/metrics.py:114-121`
3. `drawdown_time_frac` and `max_drawdown_duration_bars` in `causal_edge/validation/metrics.py`
4. Removed `pbo` / `_cpcv()` audit record from `causal_edge/validation/metrics.py`
5. `bootstrap_p` via `_bootstrap_sharpe()` in `causal_edge/validation/metrics.py`

## Current Implementation

### OOS/IS

The live contract no longer includes `oos_is`, `is_sharpe`, or `oos_sharpe`.

They were removed because a final PnL path does not tell the runtime which segment
was truly used for model discovery, tuning, or selection, so the framework could not
defensibly claim that a simple first-half/second-half split was genuine IS/OOS.

The removed implementation had split the series in half:

```python
is_sh = sharpe(pnl[:mid])
oos_sh = sharpe(pnl[mid:])
oos_is = oos_sh / is_sh if is_sh != 0 else 0
```

The removed gate had then checked:

```python
abs(oos_is) < threshold
```

### Loss years

The live contract now counts only full calendar years with negative total PnL.

Partial years still expose diagnostics (`yearly_sharpes`, `yearly_pnl`) but do not
activate the `LossYrs` gate.

### Drawdown-time stability

The live contract now measures stability using underwater time directly.

It computes:

1. `drawdown_time_frac`: fraction of bars where cumulative PnL is below its running peak
2. `max_drawdown_duration_bars`: longest consecutive underwater spell in bars

### Removed PBO family

The live contract no longer includes `pbo`, `_cpcv()`, or `T7 PBO`.

They were removed because a single strategy trade log does not carry the candidate set,
fold matrix, or model-selection event needed to define a true CPCV/PBO calculation.

### Bootstrap p-value

The code resamples the PnL path with replacement and estimates the probability that
bootstrapped Sharpe is non-positive.

This remains diagnostic-only. The live gate no longer uses a bootstrap threshold.

## Current Concerns

1. The removed OOS/IS family had no defensible runtime contract because the validator
   receives only a final PnL path, not the original research split semantics.
2. The removed gate also had a sign bug because `abs(oos_is)` could allow a negative
   out-of-sample Sharpe to pass.
3. The removed PBO family had an input-contract mismatch: validator runtime receives a
   final trade log, not the candidate-by-fold research artifact a true PBO requires.
4. `LossYrs` is now conditional on full-year coverage, so short backtests no longer
   claim year-level stability evidence they do not actually contain.
5. HFT currently leaves `max_drawdown_duration_bars_max` unknown until bar cadence is
   explicitly contracted in the profile.
6. `bootstrap_p` is still computed but no longer drives a live gate.

## Audit Questions

1. Should the OOS/IS family stay deferred unless the runtime receives explicit train/test provenance?
2. If PBO ever returns, should it require an explicit candidate-by-fold CPCV artifact
   from the external explorer instead of inferring anything from a single PnL path?
3. Should `LossYrs` eventually require more than one full year before it becomes
   applicable, or is one full year enough for this contract?
4. Should HFT remain partially unspecified here until its bar cadence is made explicit
   in profile contracts?
5. If OOS-style checks ever return, should they require explicit fold metadata rather
   than inferring IS/OOS from a final contiguous PnL path?
