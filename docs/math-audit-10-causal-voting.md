# Math Audit 10: Causal Voting

## Principle

The causal-voting family converts multiple lagged component signals into a single
position by vote direction and vote strength.

## Concrete Algorithms

1. `CausalDemoEngine.compute_signals()` in `examples/causal_demo/engine.py:33-114`
2. `ETHUSDCausalEngine.compute_signals()` in `strategies/ethusd_causal/engine.py:28-72`

## Current Implementation

### Shared pattern

Both engines follow this structure:

1. Build one directional signal per component
2. Count `n_up`, `n_down`, and `n_active`
3. Compute `vote_frac = n_up / n_active`
4. Go long only when bullish votes dominate
5. Size as `vote_frac ** 2`
6. Zero the position if conviction is below `0.75`

### Demo implementation

The example engine synthesizes target returns and component returns. For parents, the
component signal is based on lagged parent returns. For children, the signal is based
on lagged target returns.

### Live ETHUSD implementation

The live strategy loads real bars, aligns component price series to target dates, and
computes component signals from lagged rolling sums of percentage returns.

## Current Concerns

1. In `strategies/ethusd_causal/engine.py`, aligned component prices use
   `.reindex(dates).ffill().bfill()`. The `bfill()` step can introduce future data into
   earlier timestamps when a component starts later than the target series.
2. The live strategy allocates arrays using `self.n_days`, but the actual target length
   is determined after filtering and may differ.
3. The live implementation stores a `field` per component but currently always uses
   `close`, so the field metadata is not yet mathematically active.
4. The demo child-node logic is explanatory, not a literal use of child-series returns.

## Audit Questions

1. Should the live alignment logic forbid any backward fill and accept leading NaNs
   until enough history exists?
2. Should vote sizing stay quadratic, or should it become linear or capped by a
   separate risk rule?
3. Should the demo and live implementations be documented as two different algorithms:
   one pedagogical, one production-like?
