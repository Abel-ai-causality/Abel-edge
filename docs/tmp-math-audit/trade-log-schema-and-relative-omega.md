# Trade Log Schema And Relative Omega

## Why This Exists

The current validation input is a trade log with a still-minimal schema:

- `date`
- `asset_return`
- `pnl`
- `position`
- `cum_return`
- `source`

That is enough for absolute path metrics and Position-Return IC, but not enough for benchmark-aware metrics
such as "strategy Omega vs the underlying ticker's long-only Omega over the same span".

## Problem

Relative Omega needs more than a final PnL path. It needs enough information to
reconstruct the underlying asset's own return path over the same timestamps.

With the current schema, standalone validation cannot reliably know:

- which ticker the strategy traded
- which timeframe/bar cadence the log represents
- which price path generated the strategy return series

## Proposed Trade Log V2

Keep `pnl` as a stored audit artifact, but add enough market-state columns that the
validator can reconstruct benchmark returns and cross-check strategy math.

### Required core columns

- `date`
- `asset`
- `timeframe`
- `position`
- `price`
- `pnl`
- `source`

### Recommended derived columns

- `return_1bar`
- `cum_return`

## Why Store Both `price` And `pnl`

Even though `pnl` can in principle be derived from `position` and price returns, it is
still useful to store `pnl` explicitly:

1. It preserves the exact backtest artifact the strategy produced.
2. The validator can cross-check `pnl` against `position` and `price`-derived returns.
3. Benchmark-aware metrics can be computed without guessing the underlying ticker path.

## Relative Omega Concept

Once `asset`, `timeframe`, and `price` are present in the trade log, the validator can
compute two shape metrics over the same bars:

1. `strategy_omega`: empirical Omega of the strategy PnL path
2. `long_only_omega`: empirical Omega of a long-only position in the underlying ticker

Then a relative benchmark check becomes possible:

```text
strategy_omega should be materially better than long_only_omega
```

This is more meaningful than an absolute Omega threshold alone, because it asks
whether the strategy improves the underlying asset's payoff shape rather than merely
benefiting from a favorable regime.

## Contract Caveats

This should not be forced on every strategy type.

It fits best when all of the following are true:

- the strategy is directional on a primary asset
- the trade log has a clear `asset`
- the log has a clear bar cadence
- the benchmark is naturally "long one unit of the same asset"

It is a worse fit for:

- market-neutral strategies
- multi-asset portfolios
- strategies whose benchmark is not long-only exposure to one ticker

## Suggested Future Contract

1. Keep absolute Omega as a shape guardrail.
2. Keep `omega_applicable` as the no-loss applicability guard already used by the live contract.
3. Introduce `relative_omega_applicable` only when the trade log includes the benchmark
   reconstruction fields above.
4. Only then consider a conditional gate such as:

```text
strategy_omega >= long_only_omega + delta
```

The threshold `delta` would be a product-policy choice, not a mathematical identity.
