"""Receipt-bound disk cache for Abel point-in-time series."""

from __future__ import annotations

import importlib

import pandas as pd

from abel_edge.engine.adapter_registry import AbelDataFeedAdapter, FeedLoadRequest
from abel_edge.engine.cache import point_in_time_cache_covers_request
from abel_edge.plugins.abel.canonical_node import compile_canonical_node_series_spec


def _point_spec():
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
            "exchange_reference_receipt_sha256": "c" * 64,
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
    return compile_canonical_node_series_spec(
        node,
        source_receipt_sha256="e" * 64,
    )


def test_builtin_abel_adapter_reuses_exact_point_in_time_cache(tmp_path, monkeypatch):
    point_spec = _point_spec()
    calls = []

    class CanonicalModule:
        @staticmethod
        def load_canonical_node_series(**kwargs):
            calls.append(kwargs)
            frame = pd.DataFrame(
                {
                    "event_time": ["2024-01-02T05:00:00Z"],
                    "timestamp": ["2024-01-02T05:00:00Z"],
                    "value": [0.25],
                }
            )
            frame.attrs["source_receipt_sha256"] = "e" * 64
            frame.attrs["series_spec_sha256"] = point_spec.sha256
            return frame

    real_import = importlib.import_module

    def fake_import(name):
        if name == "abel_edge.plugins.abel.canonical_node_data":
            return CanonicalModule()
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    request = FeedLoadRequest(
        adapter="abel",
        kind="point_in_time_series",
        symbol=None,
        field=None,
        timeframe=None,
        start="2024-01-01",
        end="2024-01-31",
        limit=None,
        profile="daily",
        options={"cache_root": str(tmp_path)},
        strategy_id="demo",
        feed_name="graph_parent_01",
        series_spec=point_spec,
    )

    first = AbelDataFeedAdapter().load(request)
    second = AbelDataFeedAdapter().load(request)

    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second)
    assert second.attrs["source_receipt_sha256"] == "e" * 64
    assert second.attrs["series_spec_sha256"] == point_spec.sha256


def test_limited_point_in_time_cache_does_not_cover_unlimited_request():
    metadata = {
        "contract": "abel-edge.point-in-time-cache/v1",
        "series_spec_sha256": "a" * 64,
        "source_receipt_sha256": "b" * 64,
        "data_sha256": "c" * 64,
        "requested_range": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "limit": 30,
        },
    }

    assert not point_in_time_cache_covers_request(
        metadata,
        series_spec_sha256="a" * 64,
        source_receipt_sha256="b" * 64,
        start="2024-01-01",
        end="2024-12-31",
        limit=None,
    )


def test_limited_point_in_time_cache_does_not_cover_different_bounds():
    metadata = {
        "contract": "abel-edge.point-in-time-cache/v1",
        "series_spec_sha256": "a" * 64,
        "source_receipt_sha256": "b" * 64,
        "data_sha256": "c" * 64,
        "requested_range": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "limit": 30,
        },
    }

    assert not point_in_time_cache_covers_request(
        metadata,
        series_spec_sha256="a" * 64,
        source_receipt_sha256="b" * 64,
        start="2024-01-01",
        end="2024-06-30",
        limit=10,
    )
