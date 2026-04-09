# Math Audit 01: PnL Contract

## Principle

All validation logic is downstream of one base assumption:

`pnl[t]` is valid only if `position[t]` was decided using information available no
later than `t-1`.

If this contract is broken, every later metric is contaminated by look-ahead.

## Concrete Algorithms

1. Strategy output contract in `causal_edge/engine/base.py:61-75`
2. PnL computation in `causal_edge/engine/trader.py:55-62`
3. Trade-log materialization in `causal_edge/engine/ledger.py:20-46`

## Current Implementation

### Strategy output contract

`StrategyEngine.compute_signals()` must return:

- `positions`
- `dates`
- `returns`
- `prices`

The contract text in `causal_edge/engine/base.py` says `positions[t]` must be based
only on information through day `t-1`, and any rolling indicator must be shifted.

### PnL computation

`causal_edge/engine/trader.py` applies:

```python
pnl = positions * returns
pnl[0] = 0.0
```

This is mathematically correct only if the engine's `positions` array is already
causally lagged.

### Trade log

`causal_edge/engine/ledger.py` writes:

- `date`
- `pnl`
- `position`
- `cum_pnl = cumsum(pnl)`
- `source`

The trade log is then the sole input to validation.

## Current Concerns

1. The no-look-ahead rule is contractual, not mechanically enforced at runtime.
2. Validation trusts `pnl` as already correct and does not independently test
   signal timing.
3. The docs often say "daily log-return PnL", but some engines emit simple returns.
   That creates a unit mismatch between documentation and runtime behavior.

## Audit Questions

1. Do we want the framework contract to remain "engine is responsible for shift(1)"?
2. Should runtime add optional assertions that try to catch obvious timing mistakes?
3. Should the public contract say "return series" instead of "log-return series"
   unless the engine is explicitly required to emit log returns?
