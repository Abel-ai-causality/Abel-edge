# Math Audit 04: Shape And Drawdown

## Principle

Return quality is not only about mean and variance. The repo also tracks path shape,
asymmetry, and drawdown severity.

## Concrete Algorithms

1. `total_return` in `causal_edge/validation/metrics.py:96`
2. `max_dd` in `causal_edge/validation/metrics.py:88-95`
3. `calmar` in `causal_edge/validation/metrics.py:95`
4. `omega` in `causal_edge/validation/metrics.py:127-135`
5. `skew` in `causal_edge/validation/metrics.py:137-140`

## Current Implementation

### Total PnL

```python
equity = cumprod(1 + pnl)
total_return = equity[-1] - 1
```

### Max drawdown

The validation and dashboard code now compute drawdown from the compounded wealth path:

```python
equity = cumprod(1 + pnl)
dd = equity / maximum.accumulate(equity) - 1
max_dd = min(dd)
```

This yields a non-positive number.

### Calmar

```python
calmar = total_return / abs(max_dd) if max_dd < 0 else 0.0
```

### Omega

The implementation uses a zero-threshold gain/loss ratio on active observations:

```python
active = pnl[abs(pnl) > 1e-10]
omega = sum(active[active > 0]) / abs(sum(active[active < 0]))
```

If there are no losses, the payload keeps `omega = 0.0` but marks
`omega_applicable = False`, and the live gate does not count `T15 Omega` for that run.

The validator does not use benchmark-relative Omega in the live contract. That remains
deferred until the trade-log schema can reconstruct a benchmark path without guessing.

### Skew and tail diagnostics

The payload also includes `skew`, `var_5`, and `cvar_5`, but only `skew` survives in
the returned metrics payload.

## Current Concerns

1. Runtime stores `max_dd` as a non-positive drawdown fraction, while the dashboard
   displays `abs(max_dd)` as a positive percentage. The sign/display contract must stay explicit.
2. The current Omega is a simplified discrete zero-threshold version, not the more
   general continuous-threshold Omega definition.
3. The code computes `var_5` and `cvar_5` but does not expose them in the payload.
4. Relative-Omega comparisons against long-only benchmarks require richer trade-log
   schema than the current standalone validator input provides.

## Audit Questions

1. Is the current runtime-negative / display-positive MaxDD contract explicit enough for operators?
2. Is the current Omega definition sufficient for anti-clipping, or should the docs
   narrow their claim to a simple gain/loss asymmetry ratio?
3. Should benchmark-relative Omega be added only after trade logs expose enough schema
   to reconstruct long-only benchmark returns?
4. Should `var_5` and `cvar_5` either be surfaced explicitly or removed from the computation?
