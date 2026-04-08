"""Abel price data helpers."""

from __future__ import annotations

import pandas as pd

from causal_edge.plugins.abel.client import AbelClient


def fetch_bars(
    *,
    symbols: list[str],
    start=None,
    end=None,
    timeframe: str = "1d",
    limit: int | None = None,
    fields: list[str] | None = None,
    config: dict | None = None,
    client: AbelClient | None = None,
) -> pd.DataFrame:
    abel = client or AbelClient()
    api_key = abel.ensure_api_key(env_path=(config or {}).get("env_path", ".env"))
    payload = abel.fetch_bars(
        symbols=symbols,
        start=start,
        end=end,
        timeframe=timeframe,
        limit=limit,
        fields=fields,
        api_key=api_key,
    )
    return pd.DataFrame(payload)
