"""Strategy execution orchestrator. Iterates strategies.yaml, calls engines."""

from __future__ import annotations

import importlib

import click
import numpy as np

from causal_edge.engine.ledger import write_trade_log
from causal_edge.engine.price_data import resolve_price_config


def _load_engine(engine_path: str):
    """Import engine module and find the StrategyEngine subclass."""
    mod = importlib.import_module(engine_path)
    from causal_edge.engine.base import StrategyEngine

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, StrategyEngine)
            and attr is not StrategyEngine
        ):
            return attr
    raise ImportError(
        f"No StrategyEngine subclass found in '{engine_path}'. "
        f"Fix: Ensure your engine.py defines a class inheriting StrategyEngine."
    )


def run_one(strategy_cfg: dict, *, settings: dict | None = None, bars_loader=None) -> dict:
    """Run a single strategy and write its trade log.

    Args:
        strategy_cfg: Strategy dict from strategies.yaml

    Returns:
        dict with keys: id, n_days, trade_log
    """
    sid = strategy_cfg["id"]
    engine_path = strategy_cfg["engine"]
    trade_log_path = strategy_cfg["trade_log"]

    click.echo(f"  Running {sid}...")
    engine_cls = _load_engine(engine_path)
    engine = engine_cls(context=strategy_cfg)
    if bars_loader is not None:
        engine.bind_price_loader(
            bars_loader,
            resolve_price_config(settings or {}, strategy_cfg),
        )

    positions, dates, returns, prices = engine.compute_signals()

    # PnL: positions[t] * returns[t] is correct because the engine contract
    # requires positions[t] to be decided using data through t-1 only.
    # The engine is responsible for applying shift(1) to indicators.
    pnl = positions * returns
    # First day has no prior position signal
    pnl[0] = 0.0

    write_trade_log(dates, pnl, positions, trade_log_path)

    return {"id": sid, "n_days": len(dates), "trade_log": trade_log_path}


def run_all(config: dict, strategy_id: str | None = None, bars_loader=None) -> list[dict]:
    """Run all strategies (or one specific strategy) from config.

    Args:
        config: Loaded config dict from load_config()
        strategy_id: If set, run only this strategy

    Returns:
        List of result dicts from run_one()
    """
    strategies = config["strategies"]
    if strategy_id:
        strategies = [s for s in strategies if s["id"] == strategy_id]
        if not strategies:
            raise ValueError(
                f"Strategy '{strategy_id}' not found in strategies.yaml. "
                f"Available: {[s['id'] for s in config['strategies']]}"
            )

    results = []
    for s_cfg in strategies:
        result = run_one(s_cfg, settings=config.get("settings"), bars_loader=bars_loader)
        results.append(result)
        click.echo(f"    → {result['n_days']} days written to {result['trade_log']}")

    return results
