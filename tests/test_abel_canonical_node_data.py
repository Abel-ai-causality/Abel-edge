"""Live Abel materialization for canonical graph-node point series."""

from __future__ import annotations

import hashlib
import importlib
import json
import math

import pandas as pd
import pytest

from abel_edge.engine.adapter_registry import AbelDataFeedAdapter, FeedLoadRequest
from abel_edge.engine.point_in_time_series import PointInTimeSeriesContractError
from abel_edge.plugins.abel.canonical_node import compile_canonical_node_series_spec
from abel_edge.plugins.abel.canonical_node_data import (
    CanonicalNodeDataError,
    load_canonical_node_series,
)


def _digest(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_receipt(rows: list[tuple[str, float]]) -> str:
    return _digest([[day, format(value, ".17g")] for day, value in rows])


def _market_node(*, exchange_receipt: str, field: str = "close") -> dict:
    is_volume = field == "volume"
    return {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": f"canonical:AAPL:{field}",
        "family": (
            "ticker_daily_volume_log1p_change_robust_asinh"
            if is_volume
            else "ticker_daily_close_robust_asinh_return"
        ),
        "source": {
            "api_dataset": "market.price.daily",
            "field": field,
            "symbol": "AAPL",
        },
        "alignment": {
            "mode": "exchange_close_first_05:00_utc_cutoff",
            "exchange": "NASDAQ",
            "timezone": "America/New_York",
            "availability_lag_days": 0,
            "exchange_reference_receipt_sha256": exchange_receipt,
        },
        "transform": {
            "kind": "diff_log1p" if is_volume else "log_return",
            "center": 0.0,
            "scale": 1.0,
            "alpha": 1.0,
            "weekday_centers_index": None,
        },
        "release_receipt_sha256": "d" * 64,
    }


def test_builtin_abel_adapter_routes_canonical_point_in_time_series(monkeypatch):
    point_spec = compile_canonical_node_series_spec(
        _market_node(exchange_receipt="c" * 64),
        source_receipt_sha256="e" * 64,
    )
    expected = pd.DataFrame(
        {
            "event_time": ["2024-01-01T05:00:00Z"],
            "value": [0.25],
        }
    )
    expected.attrs["source_receipt_sha256"] = "e" * 64
    expected.attrs["series_spec_sha256"] = point_spec.sha256
    calls = []

    class CanonicalModule:
        @staticmethod
        def load_canonical_node_series(**kwargs):
            calls.append(kwargs)
            return expected

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
        limit=30,
        profile="daily",
        options={},
        strategy_id="demo",
        feed_name="graph_parent_01",
        series_spec=point_spec,
    )

    actual = AbelDataFeedAdapter().load(request)

    assert actual is expected
    assert calls == [
        {
            "series_spec": point_spec,
            "start": "2024-01-01",
            "end": "2024-01-31",
            "limit": 30,
            "config": {},
        }
    ]


@pytest.mark.parametrize("field", ["close", "volume"])
def test_abel_materializes_market_canonical_node(monkeypatch, field):
    exchange_rows = [
        {
            "exchange": "NASDAQ",
            "closingHour": "04:00 PM",
        }
    ]
    raw_rows = [
        {"timestamp": "2024-01-02T00:00:00Z", "symbol": "AAPL", field: 100.0},
        {"timestamp": "2024-01-03T00:00:00Z", "symbol": "AAPL", field: 110.0},
        {"timestamp": "2024-01-04T00:00:00Z", "symbol": "AAPL", field: 99.0},
    ]
    point_spec = compile_canonical_node_series_spec(
        _market_node(exchange_receipt=_digest(exchange_rows), field=field),
        source_receipt_sha256=_raw_receipt(
            [
                ("2024-01-02", 100.0),
                ("2024-01-03", 110.0),
                ("2024-01-04", 99.0),
            ]
        ),
    )
    calls = []

    def fake_fetch_bars(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(raw_rows)

    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data.fetch_bars",
        fake_fetch_bars,
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data._fetch_exchange_reference",
        lambda **_: exchange_rows,
    )

    frame = load_canonical_node_series(
        series_spec=point_spec,
        start="2024-01-02",
        end="2024-01-04",
        limit=None,
        config={},
    )

    assert list(frame["event_time"]) == [
        pd.Timestamp("2024-01-04T05:00:00Z"),
    ]
    assert list(frame["value"]) == pytest.approx(
        [
            math.asinh(
                math.log1p(110.0) - math.log1p(100.0)
                if field == "volume"
                else math.log(110.0 / 100.0)
            ),
        ]
    )
    assert frame.attrs["source_receipt_sha256"] == point_spec.payload[
        "provenance"
    ]["source_receipt_sha256"]
    assert frame.attrs["series_spec_sha256"] == point_spec.sha256
    assert calls[0]["symbols"] == ["AAPL"]
    assert calls[0]["fields"] == [field]


def test_abel_rejects_canonical_source_receipt_drift(monkeypatch):
    exchange_rows = [{"exchange": "NASDAQ", "closingHour": "04:00 PM"}]
    point_spec = compile_canonical_node_series_spec(
        _market_node(exchange_receipt=_digest(exchange_rows)),
        source_receipt_sha256="e" * 64,
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data.fetch_bars",
        lambda **_: pd.DataFrame(
            [
                {
                    "timestamp": "2024-01-02T00:00:00Z",
                    "symbol": "AAPL",
                    "close": 100.0,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data._fetch_exchange_reference",
        lambda **_: exchange_rows,
    )

    with pytest.raises(CanonicalNodeDataError, match="source receipt drift"):
        load_canonical_node_series(
            series_spec=point_spec,
            start="2024-01-02",
            end="2024-01-04",
            limit=None,
            config={},
        )


def test_abel_materializes_catalog_canonical_node(monkeypatch):
    schema = {"fields": [{"name": "date"}, {"name": "country"}, {"name": "value"}]}
    rows = [
        {
            "timestamp": "2024-01-01T00:00:00Z",
            "node_id": "catalog:demo:value:US",
            "value": 12.0,
        },
        {
            "timestamp": "2024-01-02T00:00:00Z",
            "node_id": "catalog:demo:value:US",
            "value": 15.0,
        },
    ]
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "catalog:demo:value:US",
        "family": "catalog_diff_then_robust_asinh_deseason",
        "source": {
            "api_dataset": "demo.daily",
            "time_field": "date",
            "measure": "value",
            "measure_field": "value",
            "raw_json_field": None,
            "keys": ["country"],
            "key_values": {"country": "US"},
            "key_fields": {"country": "country"},
            "server_filters": {},
            "aggregation": "mean",
        },
        "alignment": {
            "mode": "source_date_plus_availability_lag_to_05:00_utc",
            "availability_lag_days": 2,
            "time_policy": "source_date",
        },
        "transform": {
            "kind": "diff",
            "alpha": 1.0,
            "center": 0.0,
            "scale": 1.0,
            "weekday_centers_index": 7,
            "weekday_centers": [0.0] * 7,
        },
        "schema_sha256": _digest(schema),
        "release_receipt_sha256": "d" * 64,
    }
    point_spec = compile_canonical_node_series_spec(
        node,
        source_receipt_sha256=_raw_receipt(
            [("2024-01-01", 12.0), ("2024-01-02", 15.0)]
        ),
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data.fetch_node_series",
        lambda **_: pd.DataFrame(rows),
    )

    frame = load_canonical_node_series(
        series_spec=point_spec,
        start="2024-01-01",
        end="2024-01-04",
        limit=None,
        config={},
    )

    assert list(frame["event_time"]) == [pd.Timestamp("2024-01-02T05:00:00Z")]
    assert list(frame["value"]) == pytest.approx([math.asinh(3.0)])


def test_canonical_node_mode_rejects_rows_for_a_different_node(monkeypatch):
    schema = {"fields": []}
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "catalog:demo:value:US",
        "family": "catalog_diff_then_robust_asinh_deseason",
        "source": {
            "api_dataset": "demo.daily",
            "time_field": "date",
            "measure": "value",
        },
        "alignment": {
            "mode": "source_date_plus_availability_lag_to_05:00_utc",
            "availability_lag_days": 2,
            "time_policy": "source_date",
        },
        "transform": {
            "kind": "diff",
            "alpha": 1.0,
            "center": 0.0,
            "scale": 1.0,
            "weekday_centers_index": None,
        },
        "schema_sha256": _digest(schema),
        "release_receipt_sha256": "d" * 64,
    }
    point_spec = compile_canonical_node_series_spec(
        node,
        source_receipt_sha256="e" * 64,
    )
    monkeypatch.setattr(
        "abel_edge.plugins.abel.canonical_node_data.fetch_node_series",
        lambda **_: pd.DataFrame(
            [
                {
                    "timestamp": "2024-01-02T00:00:00Z",
                    "node_id": "catalog:demo:value:CA",
                    "value": 100.0,
                }
            ]
        ),
    )

    with pytest.raises(CanonicalNodeDataError, match="unexpected node_id"):
        load_canonical_node_series(
            series_spec=point_spec,
            start="2024-01-02",
            end="2024-01-04",
            limit=None,
            config={},
        )


def test_catalog_transform_requires_frozen_weekday_centers():
    schema = {"fields": []}
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "catalog:demo:value:US",
        "family": "catalog_diff_then_robust_asinh_deseason",
        "source": {
            "api_dataset": "demo.daily",
            "time_field": "date",
            "measure": "value",
        },
        "alignment": {
            "mode": "source_date_plus_availability_lag_to_05:00_utc",
            "availability_lag_days": 2,
            "time_policy": "source_date",
        },
        "transform": {
            "kind": "diff",
            "alpha": 1.0,
            "center": 0.0,
            "scale": 1.0,
            "weekday_centers_index": 7,
        },
        "schema_sha256": _digest(schema),
        "release_receipt_sha256": "d" * 64,
    }

    with pytest.raises(PointInTimeSeriesContractError, match="weekday_centers"):
        compile_canonical_node_series_spec(
            node,
            source_receipt_sha256="e" * 64,
        )
