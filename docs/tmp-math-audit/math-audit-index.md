# Math Audit Index

This dossier breaks the repo's math-related behavior into reviewable documents.
Each document is organized as:

1. Principle
2. Concrete algorithms in the repo
3. Current implementation
4. Current concerns
5. Audit questions

## Review Order

1. [PnL Contract](tmp-math-audit/math-audit-01-pnl-contract.md)
2. [Profile Detection](tmp-math-audit/math-audit-02-profile-detection.md)
3. [Ratio Metrics](tmp-math-audit/math-audit-03-ratio-metrics.md)
4. [Shape And Drawdown](tmp-math-audit/math-audit-04-shape-drawdown.md)
5. [Generalization And Stability](tmp-math-audit/math-audit-05-generalization-stability.md)
6. [Rank Metrics](tmp-math-audit/math-audit-06-rank-metrics.md)
7. [Gates And Score Semantics](tmp-math-audit/math-audit-07-gates-and-score.md)
8. [SMA Crossover](tmp-math-audit/math-audit-08-sma-crossover.md)
9. [Walk-Forward ML](tmp-math-audit/math-audit-09-walk-forward-ml.md)
10. [Causal Voting](tmp-math-audit/math-audit-10-causal-voting.md)
11. [Trade Log Schema And Relative Omega](tmp-math-audit/trade-log-schema-and-relative-omega.md)

## Scope

This audit set covers the two math surfaces requested for review:

- Validation metrics and gate logic under `causal_edge/validation/`
- Strategy signal generation under `examples/` and `strategies/`

It does not treat the dashboard as a primary audit surface. The dashboard computes
derived summary metrics, but it is not the repo's admission gate.

## Live Vs Example Code

- Live validation contract: `causal_edge/validation/metrics.py`, `causal_edge/validation/gate.py`
- Live strategy: `strategies/ethusd_causal/engine.py`
- Example strategies: `examples/sma_crossover/engine.py`, `examples/momentum_ml/engine.py`, `examples/causal_demo/engine.py`

## Working Rule For Review

The point of these docs is not to defend the current code. The point is to make
the current code explicit enough that a human can decide, line by line, whether
the math is acceptable, needs a narrower claim, or needs to change.

## Working Location

The math-audit documents live under `docs/tmp-math-audit/` while the review is in
progress. Long-lived validation and timing contract facts belong in
`docs/validation-audit-matrix.md` and operator-facing docs.
