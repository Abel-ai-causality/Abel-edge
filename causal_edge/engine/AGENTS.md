# Engine Subsystem

Strategy execution framework. All engines implement `StrategyEngine` ABC from `causal_edge/engine/base.py`.

## I want to...

### Create a new engine
1. Copy `examples/sma_crossover/engine.py` as starting point
2. Implement `compute_signals()` -> (positions, dates, prices)
3. Implement `get_latest_signal()` -> dict with at least `position` key
4. All features must use `shift(1)` — zero look-ahead tolerance
5. Register in `strategies.yaml` with engine module path

### Understand the execution flow
```
strategies.yaml -> config.py -> trader.py -> engine.compute_signals() -> ledger.py -> CSV
```

### Debug "engine not importable"
1. Check `strategies.yaml` engine path matches actual module path
2. Check `__init__.py` exists in the strategy directory
3. Run: `python -c "import strategies.my_strategy.engine"`
4. `make test` — `TestEngineModuleImportable` shows the exact error

## Key Files
- `base.py` — `StrategyEngine` ABC (read this first)
- `trader.py` — iterates strategies, calls engines, writes trade logs
- `ledger.py` — trade log CSV read/write
