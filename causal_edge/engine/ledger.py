"""Trade log read/write. Single source of truth for trade log CSV format."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("date", "pnl", "position", "cum_return", "source")


def read_trade_log(path: str | Path) -> pd.DataFrame:
    """Read a trade log CSV. Returns DataFrame with standard columns."""
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def write_trade_log(
    dates: pd.DatetimeIndex,
    asset_returns: np.ndarray,
    pnl: np.ndarray,
    positions: np.ndarray,
    path: str | Path,
    source: str = "backfill",
) -> None:
    """Write a trade log CSV from strategy output arrays.

    Args:
        dates: Trading dates
        asset_returns: Daily simple returns of the underlying asset
        pnl: Daily PnL (position * returns)
        positions: Daily position sizes
        path: Output CSV path
        source: "backfill" or "live"
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(
        {
            "date": dates,
            "asset_return": asset_returns,
            "pnl": pnl,
            "position": positions,
            "cum_return": np.cumprod(1.0 + pnl) - 1.0,
            "source": source,
        }
    )
    df.to_csv(path, index=False)
