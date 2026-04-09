# Validation Audit Matrix

## Scope

This is the finalized audit ledger for the `validate` subsystem.
It records the audited live contract after remediation of gates, metrics, profile wiring, score semantics, and public documentation.

### Final Verdict Vocabulary
- `keep` — retained in the audited live contract
- `rebuild` — retained, but algorithm/semantics were materially corrected
- `defer` — removed from the live contract and tracked for future re-entry
- `clarify` — retained, but the primary remediation was contract/applicability clarification

## Runtime Surfaces

| Surface | File | Audited state |
|---|---|---|
| Metric computation | `causal_edge/validation/metrics.py` | Live metric payload includes explicit `ic_applicable` semantics |
| Gate evaluation | `causal_edge/validation/metrics.py` | Live failures are T6/T7/T13/T14/T15-Lo/T15-Omega/T15-MaxDD plus `PnL floor`, `Sharpe/Lo`, and conditional `IC`/`IC stab` |
| Result contract | `causal_edge/validation/gate.py` | `validate_strategy()` returns `verdict`, `score`, `failures`, `metrics`, `triangle`, `profile` |
| Score denominator | `causal_edge/validation/gate.py` | `_count_total()` yields `9` checks base, `11` when `ic_applicable` is true |
| Profiles | `causal_edge/validation/profiles/*.yaml` | Only justified live keys remain; orphan keys were removed and deferred |
| CLI/report contract | `causal_edge/cli.py`, `causal_edge/validation/gate.py` | No-position verbose output omits IC-family diagnostics |
| Public claims | `README.md`, `CAPABILITY.md`, `causal_edge/validation/AGENTS.md`, `causal_edge/validation/__init__.py` | Active public wording matches the audited live contract |

## Contract Summary

| Item | Final state | Evidence |
|---|---|---|
| Score denominator | `9` without IC applicability, `11` with IC applicability | `causal_edge/validation/gate.py`, `tests/test_validation_contract.py` |
| Removed OOS/IS family | `oos_is`, `is_sharpe`, `oos_sharpe`, `T12 OOS/IS`, and `validation.oos_is_min` were removed from the live contract and deferred | `causal_edge/validation/metrics.py`, profile YAMLs, `causal_edge/validation/deferred_registry.yaml` |
| IC applicability | Explicit `metrics["ic_applicable"]` controls IC-family counting and failures | `causal_edge/validation/metrics.py`, `tests/test_validation_contract.py` |
| Removed bootstrap gate | No longer affects live failures or denominator | `causal_edge/validation/metrics.py`, `causal_edge/validation/gate.py`, `causal_edge/validation/deferred_registry.yaml` |
| Orphan profile keys | Removed from YAML and tracked in deferred registry | profile YAMLs + `causal_edge/validation/deferred_registry.yaml` |
| Public docs | Legacy `15/21` active claims removed from current public surfaces | `README.md`, `CAPABILITY.md`, `causal_edge/validation/AGENTS.md`, `CHANGELOG.md` |

## Metric Decisions

| Metric | Verdict | Rationale |
|---|---|---|
| `sharpe` | keep | Core retained ratio metric |
| `lo_adjusted` | rebuild | Retained ratio metric, simplified to a profile-aware lag-1 serial-correlation penalty |
| `sortino` | keep | Retained as diagnostic payload metric |
| `total_pnl` | keep | Retained as live anti-gaming input |
| `max_dd` | keep | Retained as live gate and keep/discard input |
| `calmar` | rebuild | Retained but zero-drawdown sentinel normalized to `0.0` |
| `dsr` | rebuild | Retained as a live overfitting gate with operator-supplied `dsr_trials` override and profile-default fallback |
| `pbo` | keep | Retained live gate metric |
| `oos_is` | defer | Removed from the live payload because a final PnL path does not establish defensible in-sample/out-of-sample provenance |
| `loss_years` | keep | Retained live gate metric |
| `neg_roll_frac` | keep | Retained live gate metric |
| `omega` | rebuild | Retained but no-loss sentinel normalized to `0.0` |
| `skew` | rebuild | Retained diagnostic metric with constant-series normalization |
| `sharpe_lo_ratio` | keep | Retained anti-gaming gate input |
| `bootstrap_p` | clarify | Retained as diagnostic metric only; removed from live gate logic |
| `ic` | clarify | Retained with explicit applicability semantics |
| `ic_hit_rate` | clarify | Retained diagnostic metric, shown only when IC is applicable |
| `ic_stability` | clarify | Retained conditional gate metric under explicit applicability semantics |
| `ic_monthly_mean` | clarify | Retained diagnostic metric under explicit applicability semantics |
| `ic_applicable` | keep | Added as explicit contract signal for IC-family applicability |
| `active_days` | keep | Retained diagnostic sufficiency metric |
| `total_days` | keep | Retained diagnostic sufficiency metric |
| `yearly_sharpes` | keep | Retained supporting diagnostic structure |
| `is_sharpe` | defer | Removed with the OOS/IS family because split-half Sharpe diagnostics no longer have a live contract consumer |
| `oos_sharpe` | defer | Removed with the OOS/IS family because split-half Sharpe diagnostics no longer have a live contract consumer |
| `hill_alpha` | defer | Removed from live payload; no gate/report/public contract |
| `cvar_var_ratio` | defer | Removed from live payload; no gate/report/public contract |

## Gate Decisions

| Gate / failure | Verdict | Rationale |
|---|---|---|
| `T6 DSR` | keep | Live documented overfitting gate; caller may override exploration count via `dsr_trials` |
| `T7 PBO` | keep | Live documented gate |
| `T12 OOS/IS` | defer | Removed from live validation because half-split Sharpe ratio lacked a defensible sample-in/sample-out contract |
| `T13 NegRoll` | keep | Live documented gate |
| `T14 LossYrs` | keep | Live documented gate |
| `T15 Lo` | keep | Live documented gate |
| `T15 Omega` | keep | Live documented gate |
| `T15 MaxDD` | keep | Live documented gate |
| `PnL floor` | keep | Live anti-gaming gate; retained and documented as non-T-coded failure |
| `Sharpe/Lo` | keep | Live anti-gaming gate; retained and documented as non-T-coded failure |
| `IC` | clarify | Live only when `ic_applicable` is true |
| `IC stab` | clarify | Live only when `ic_applicable` is true |
| `Bootstrap p` | defer | Removed from live gate because no profile-configurable threshold or public contract existed |

## Profile Key Decisions

| Key family | Verdict | Final state |
|---|---|---|
| `validation.dsr_K` | keep | Retained as the default exploration-count prior when `dsr_trials` is not explicitly provided |
| `validation.periods_per_year` | keep | Added as the profile-supplied annualization contract for Sharpe-family metrics |
| `validation.oos_is_min` | defer | Removed from live YAML after T12 OOS/IS was dropped from the contract |
| `validation.permutation_*` | defer | Removed from live YAML; tracked in deferred registry |
| `validation.look_ahead_*` | defer | Removed from live YAML; tracked in deferred registry |
| `anti_gaming.relative_pnl_drop_max` | defer | Removed from live YAML; tracked in deferred registry |

## Public Claim Crosswalk

| Surface | Final audited message |
|---|---|
| `README.md` | Validation uses the audited live contract; no active `15-test` or `21`-style wording remains |
| `CAPABILITY.md` | Examples describe `9/11`-style applicable-gate denominators and migration notes |
| `causal_edge/validation/AGENTS.md` | Operator guidance references the audited live contract and deferred registry |
| `causal_edge/validation/__init__.py` | Exported docstring describes applicable-gate denominator semantics |
| `CHANGELOG.md` | Migration and comparability notes explain denominator and sentinel changes |

## Deferred Registry Alignment

The following items were removed from the live contract and are tracked in `causal_edge/validation/deferred_registry.yaml`:

- `hill_alpha`
- `cvar_var_ratio`
- `oos_is`
- `is_sharpe`
- `oos_sharpe`
- `T12 OOS/IS`
- `validation.oos_is_min`
- `Bootstrap p` gate
- `validation.permutation_trials`
- `validation.permutation_p_max`
- `validation.look_ahead_mag_corr_max`
- `validation.look_ahead_hit_rate_max`
- `anti_gaming.relative_pnl_drop_max`

## Migration Summary

| Item | Change type | Migration note |
|---|---|---|
| Score denominator narrative | mathematical correction | Live contract is `9/11` by applicable-gate scope, not legacy `15` / `20` / `21` wording |
| `OOS/IS` family | removal/defer | `oos_is`, `is_sharpe`, `oos_sharpe`, `T12 OOS/IS`, and `validation.oos_is_min` were removed because a final PnL path could not justify a true IS/OOS claim |
| `lo_adjusted` simplification | mathematical correction | Fixed-252, 10-lag approximation was replaced with a profile-aware lag-1 serial-correlation penalty |
| `dsr_trials` override | clarification | DSR now accepts caller-supplied exploration counts and falls back to the profile default only when no explicit declaration is provided |
| `omega` no-loss sentinel | mathematical correction | `999` → `0.0`; historical reports using sentinel values are not directly comparable |
| `calmar` zero-drawdown sentinel | mathematical correction | `999` → `0.0`; historical reports using sentinel values are not directly comparable |
| `skew` constant-series sentinel | clarification | `NaN` → `0.0` for deterministic payload semantics |
| `Bootstrap p` gate | removal/defer | Removed from live validation and tracked in deferred registry pending future contract definition |
| `validation.permutation_*` | removal/defer | Removed from live profiles and tracked in deferred registry |
| `validation.look_ahead_*` | removal/defer | Removed from live profiles and tracked in deferred registry |
| `anti_gaming.relative_pnl_drop_max` | removal/defer | Removed from live profiles and tracked in deferred registry |
| IC applicability semantics | clarification | Explicit `ic_applicable` flag replaces implicit zero-value inference |
