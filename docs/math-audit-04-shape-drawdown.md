# Math Audit 04: Shape And Drawdown

## Principle

Return quality is not only about mean and variance. The repo also tracks path shape,
asymmetry, and drawdown severity.

## Concrete Algorithms

1. `total_pnl` in `causal_edge/validation/metrics.py:96`
2. `max_dd` in `causal_edge/validation/metrics.py:88-95`
3. `calmar` in `causal_edge/validation/metrics.py:95`
4. `omega` in `causal_edge/validation/metrics.py:127-135`
5. `skew` in `causal_edge/validation/metrics.py:137-140`

## Current Implementation

### Total PnL

```python
total_pnl = cumsum(pnl)[-1]
```

### Max drawdown

The validation code computes drawdown in cumulative-PnL space:

```python
cum = cumsum(pnl)
dd = cum - maximum.accumulate(cum)
max_dd = min(dd)
```

This yields a non-positive number.

### Calmar

```python
calmar = total_pnl / abs(max_dd) if max_dd < 0 else 0.0
```

### Omega

The implementation uses a zero-threshold gain/loss ratio on active observations:

```python
active = pnl[abs(pnl) > 1e-10]
omega = sum(active[active > 0]) / abs(sum(active[active < 0]))
```

If there are no losses, the implementation returns `0.0`.

### Skew and tail diagnostics

The payload also includes `skew`, `var_5`, and `cvar_5`, but only `skew` survives in
the returned metrics payload.

## Current Concerns

1. Validation `max_dd` is in cumulative-return space, but dashboard `max_dd` is a
   percentage drawdown on an equity curve. The repo therefore has two different
   drawdown meanings.
2. `omega = 0.0` when there are no losses is a deterministic sentinel, not the usual
   mathematical limit.
3. The code computes `var_5` and `cvar_5` but does not expose them in the payload.
4. The current Omega is a simplified discrete zero-threshold version, not the more
   general continuous-threshold Omega definition.

## Audit Questions

1. Should validation and dashboard share one drawdown definition?
2. Is the current Omega definition sufficient for anti-clipping, or should the docs
   narrow their claim to a simple gain/loss asymmetry ratio?
3. Should `var_5` and `cvar_5` either be surfaced explicitly or removed from the computation?
