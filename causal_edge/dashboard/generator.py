"""Dashboard HTML generator — reads config + trade logs, renders Jinja2 templates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader

from causal_edge.config import load_config
from causal_edge.dashboard._helpers import fmt_pnl_pct, fmt_dollar
from causal_edge.dashboard.components import (
    compute_metrics,
    equity_chart,
    position_chart,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_trade_log(path: str) -> pd.DataFrame | None:
    """Load trade log CSV, return None if not found."""
    try:
        return pd.read_csv(path, parse_dates=["date"])
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None


def _prepare_strategy(s_cfg: dict) -> dict:
    """Prepare data dict for a single strategy."""
    df = _load_trade_log(s_cfg["trade_log"])
    if df is None or len(df) == 0:
        return {
            "id": s_cfg["id"],
            "name": s_cfg["name"],
            "color": s_cfg["color"],
            "asset": s_cfg["asset"],
            "has_data": False,
            "metrics": {},
            "equity_json": "{}",
            "position_json": "{}",
        }

    pnl = df["pnl"].values.astype(float)
    positions = (
        df["position"].values.astype(float) if "position" in df.columns else np.zeros(len(pnl))
    )
    dates = pd.DatetimeIndex(df["date"])
    cum_return = np.cumprod(1.0 + pnl) - 1.0

    metrics = compute_metrics(pnl)

    return {
        "id": s_cfg["id"],
        "name": s_cfg["name"],
        "color": s_cfg["color"],
        "asset": s_cfg["asset"],
        "has_data": True,
        "metrics": metrics,
        "equity_json": equity_chart(dates, cum_return, s_cfg["name"], s_cfg["color"]),
        "position_json": position_chart(dates, positions, s_cfg["name"], s_cfg["color"]),
        "latest_date": str(dates[-1].date()) if len(dates) > 0 else "N/A",
        "latest_position": float(positions[-1]) if len(positions) > 0 else 0,
    }


def generate(config_path: str, output_path: str) -> None:
    """Generate dashboard.html from config and trade logs.

    Args:
        config_path: Path to strategies.yaml
        output_path: Path to write dashboard.html
    """
    cfg = load_config(config_path)
    strategies = [_prepare_strategy(s) for s in cfg["strategies"]]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
    )
    # Register helper functions
    env.globals["fmt_pnl_pct"] = fmt_pnl_pct
    env.globals["fmt_dollar"] = fmt_dollar

    template = env.get_template("base.html")
    html = template.render(
        strategies=strategies,
        settings=cfg["settings"],
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    Path(output_path).write_text(html, encoding="utf-8")
