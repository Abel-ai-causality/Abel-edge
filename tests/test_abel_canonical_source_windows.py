"""Frozen receipt replay remains independent from runtime visibility windows."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from abel_edge.plugins.abel.canonical_node import (
    compile_canonical_node_series_spec,
    compile_cap_node_series_spec,
)
from abel_edge.plugins.abel.canonical_node_data import (
    cap_node_series_receipt,
    load_canonical_node_series,
)


NODE_ID = "health.openfda.drug.events:event_count#96bc3e82"


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _market_spec(exchange_rows, raw_rows):
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "canonical:AAPL:close",
        "family": "ticker_daily_close_robust_asinh_return",
        "source": {
            "api_dataset": "market.price.daily",
            "field": "close",
            "symbol": "AAPL",
        },
        "alignment": {
            "mode": "exchange_close_first_05:00_utc_cutoff",
            "exchange": "NASDAQ",
            "timezone": "America/New_York",
            "availability_lag_days": 0,
            "exchange_reference_receipt_sha256": _digest(exchange_rows),
        },
        "transform": {
            "kind": "log_return",
            "center": 0.0,
            "scale": 1.0,
            "alpha": 1.0,
            "weekday_centers_index": None,
        },
        "release_receipt_sha256": "d" * 64,
    }
    receipt_rows = [
        [row["timestamp"][:10], format(row["close"], ".17g")] for row in raw_rows
    ]
    return compile_canonical_node_series_spec(
        node,
        source_receipt_sha256=_digest(receipt_rows),
    )


def test_market_runtime_window_replays_frozen_receipt_window(monkeypatch):
    exchange_rows = [{"exchange": "NASDAQ", "closingHour": "04:00 PM"}]
    raw_rows = [
        {"timestamp": "2024-01-02T00:00:00Z", "symbol": "AAPL", "close": 100.0},
        {"timestamp": "2024-06-03T00:00:00Z", "symbol": "AAPL", "close": 110.0},
        {"timestamp": "2024-06-04T00:00:00Z", "symbol": "AAPL", "close": 121.0},
        {"timestamp": "2024-12-02T00:00:00Z", "symbol": "AAPL", "close": 133.1},
    ]
    calls = []

    def fake_fetch_bars(**kwargs):
        calls.append(kwargs)
        frame = pd.DataFrame(raw_rows)
        timestamps = pd.to_datetime(frame["timestamp"], utc=True)
        return frame[
            (timestamps >= pd.to_datetime(kwargs["start"], utc=True))
            & (timestamps <= pd.to_datetime(kwargs["end"], utc=True))
        ].copy()

    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data.fetch_bars", fake_fetch_bars
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data._fetch_exchange_reference",
        lambda **_: exchange_rows,
    )

    frame = load_canonical_node_series(
        series_spec=_market_spec(exchange_rows, raw_rows),
        start="2024-06-01",
        end="2024-06-30",
        limit=1,
        config={"source_start": "2024-01-01", "source_end": "2024-12-31"},
    )

    assert (calls[0]["start"], calls[0]["end"], calls[0]["limit"]) == (
        "2024-01-01",
        "2024-12-31",
        200_000,
    )
    assert list(frame["event_time"]) == [pd.Timestamp("2024-06-05T05:00:00Z")]


def test_cap_runtime_window_replays_frozen_receipt_window(monkeypatch):
    rows = [
        {"timestamp": "2026-01-02T00:00:00Z", "event_time": "2026-01-01T00:00:00Z", "node_id": NODE_ID, "value": 10.0},
        {"timestamp": "2026-05-01T00:00:00Z", "event_time": "2026-04-30T00:00:00Z", "node_id": NODE_ID, "value": 21.0},
        {"timestamp": "2026-05-02T00:00:00Z", "event_time": "2026-05-02T00:00:00Z", "node_id": NODE_ID, "value": 25.0},
        {"timestamp": "2026-12-02T00:00:00Z", "event_time": "2026-12-01T00:00:00Z", "node_id": NODE_ID, "value": 30.0},
    ]
    calls = []

    def fake_fetch_node_series(**kwargs):
        calls.append(kwargs)
        frame = pd.DataFrame(rows)
        timestamps = pd.to_datetime(frame["timestamp"], utc=True)
        return frame[
            (timestamps >= pd.to_datetime(kwargs["start"], utc=True))
            & (timestamps <= pd.to_datetime(kwargs["end"], utc=True))
        ].copy()

    monkeypatch.setattr(
        "abel_edge.plugins.abel.cap_node_series.fetch_node_series",
        fake_fetch_node_series,
    )
    spec = compile_cap_node_series_spec(
        node_id=NODE_ID,
        graph_ref={"graph_id": "abel-main", "graph_version": "CausalNodeV4"},
        source_receipt_sha256=cap_node_series_receipt(rows, node_id=NODE_ID),
    )

    frame = load_canonical_node_series(
        series_spec=spec,
        start="2026-05-01",
        end="2026-05-31",
        limit=1,
        config={"source_start": "2026-01-01", "source_end": "2026-12-31"},
    )

    assert (calls[0]["start"], calls[0]["end"], calls[0]["limit"]) == (
        "2026-01-01",
        "2026-12-31",
        None,
    )
    assert list(frame["timestamp"]) == ["2026-05-02T00:00:00Z"]
    assert list(frame["value"]) == [25.0]
