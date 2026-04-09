# Math Audit 01: PnL Contract

## Principle

All validation logic is downstream of one base assumption:

`pnl[t]` is valid only if `position[t]` was decided using information available no
later than `t-1`.

If this contract is broken, every later metric is contaminated by look-ahead.

## Concrete Algorithms

1. Strategy output contract in `causal_edge/engine/base.py:61-75`
2. PnL computation in `causal_edge/engine/trader.py:55-68`
3. Trade-log materialization in `causal_edge/engine/ledger.py:20-51`

## Current Implementation

### Strategy output contract

`StrategyEngine.compute_signals()` must return:

- `positions`
- `dates`
- `prices`

The contract text in `causal_edge/engine/base.py` says `positions[t]` must be based
only on information through day `t-1`, and any rolling indicator must be shifted.

### Timing contract

The live engine/validator pipeline implies this exact bar-by-bar relationship:

```text
price[t-1], price[t] -> asset_return[t]
information through t-1 -> position[t]
position[t] * asset_return[t] -> pnl[t]
cumprod(1 + pnl[:t]) - 1 -> cum_return[t]
```

This means:

- `asset_return[t]` is the return realized over the interval from `t-1` to `t`
- `position[t]` is the exposure chosen before `asset_return[t]` is realized
- `pnl[t]` is the realized payoff of that pre-chosen exposure over that interval

So the allowed dependency rule is:

- `position[t]` may depend on `price[:t]` only through information available at `t-1`
- `position[t]` may depend on `asset_return[:t]` only through returns up to `t-1`
- `position[t]` must not depend on `price[t]` or `asset_return[t]`

Equivalently: first choose `position[t]`, then the market realizes `asset_return[t]`,
then the system books `pnl[t]`.

### PnL computation

`causal_edge/engine/trader.py` applies:

```python
pnl = positions * returns
pnl[0] = 0.0
```

This is mathematically correct only if the engine's `positions` array is already
causally lagged.

The repo therefore assumes `position[t]` means "hold this exposure over the return
interval ending at `t`", not "decide this exposure after seeing bar `t`".

### Trade log

`causal_edge/engine/ledger.py` writes:

- `date`
- `asset_return`
- `pnl`
- `position`
- `cum_return = cumprod(1 + pnl) - 1`
- `source`

The trade log is then the sole input to validation.

## Current Concerns

1. The no-look-ahead rule is contractual, not mechanically enforced at runtime.
2. Validation trusts `pnl` as already correct and does not independently test
   signal timing.
3. The contract must stay explicit that `pnl` is a simple-return strategy series,
   with path metrics derived from `cumprod(1 + pnl)` rather than `cumsum(pnl)`.
4. Any feature pipeline that uses `price[t]`, `asset_return[t]`, or backward-fill-like
   alignment when constructing `position[t]` breaks the contract even if the final CSV
   looks structurally valid.

## Audit Checklist

When auditing a strategy, apply these checks directly:

1. Every feature used to determine `position[t]` must be lagged by at least one bar.
2. No decision path may use `price[t]` or `asset_return[t]` when setting `position[t]`.
3. No alignment step may propagate future observations backward into earlier timestamps.
4. The interpretation `pnl[t] = position[t] * asset_return[t]` must remain true for the
   emitted trade log.

## Audit Questions

1. Do we want the framework contract to remain "engine is responsible for shift(1)"?
2. Should runtime add optional assertions that try to catch obvious timing mistakes?
3. Should the public contract consistently say "simple-return strategy series" now
   that path metrics are derived from compounding rather than additive accumulation?
