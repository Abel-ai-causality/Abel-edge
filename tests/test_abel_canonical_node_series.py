"""Canonical graph nodes compile into the generic Edge series contract."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from abel_edge.engine.adapter_registry import register_adapter
from abel_edge.engine.base import StrategyEngine
from abel_edge.engine.point_in_time_series import PointInTimeSeriesContractError
from abel_edge.plugins.abel.canonical_node import compile_canonical_node_series_spec


def _market_node() -> dict:
    return {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "ticker:AAPL:close",
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
            "availability_lag_days": 1,
            "exchange_reference_receipt_sha256": "c" * 64,
        },
        "transform": {
            "kind": "log_return",
            "center": 0.0,
            "scale": 1.2,
            "alpha": 0.8,
            "weekday_centers_index": None,
        },
        "release_receipt_sha256": "d" * 64,
    }


def test_market_node_compiles_without_turning_node_identity_into_a_symbol():
    spec = compile_canonical_node_series_spec(
        _market_node(),
        source_receipt_sha256="e" * 64,
    )
    payload = spec.to_mapping()

    assert payload["contract"] == "abel-edge.point-in-time-series/v1"
    assert payload["series_id"] == "ticker:AAPL:close"
    assert payload["source"]["adapter"] == "abel"
    assert payload["source"]["request"]["family"].startswith("ticker_daily_close")
    assert payload["source"]["request"]["retrieval_mode"] == "symbol"
    assert payload["source"]["request"]["source"]["symbol"] == "AAPL"
    assert payload["schema"] == {
        "event_time_field": "event_time",
        "value_field": "value",
    }
    assert payload["availability"] == {"mode": "calendar_days", "lag_days": 1}
    assert payload["materialization"]["grid_time_utc"] == "05:00:00"
    assert payload["materialization"]["alignment_policy"] == "native_only"
    assert payload["transforms"][0]["parameters"]["kind"] == "log_return"
    assert payload["provenance"]["alignment_receipt_sha256"] == "c" * 64


@pytest.mark.parametrize(
    ("family", "field"),
    [
        ("ticker_daily_close_robust_asinh_return", "volume"),
        ("ticker_daily_volume_log1p_change_robust_asinh", "close"),
        ("ticker_daily_unknown", "close"),
    ],
)
def test_market_node_family_must_match_its_adjusted_symbol_field(family, field):
    node = _market_node()
    node["family"] = family
    node["source"]["field"] = field

    with pytest.raises(PointInTimeSeriesContractError, match="market family"):
        compile_canonical_node_series_spec(
            node,
            source_receipt_sha256="e" * 64,
        )


def test_catalog_node_keeps_dataset_measure_keys_and_schema_receipt():
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "catalog:weather:pm25",
        "family": "catalog_diff_then_robust_asinh_deseason",
        "source": {
            "api_dataset": "weather.openaq.sensor.daily",
            "time_field": "date",
            "measure": "pm25",
            "measure_field": "value",
            "raw_json_field": "rawJson",
            "keys": ["sensorId"],
            "key_values": {"sensorId": 42},
            "key_fields": {"sensorId": "sensorId"},
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
        "schema_sha256": "f" * 64,
        "release_receipt_sha256": "d" * 64,
    }

    spec = compile_canonical_node_series_spec(
        node,
        source_receipt_sha256="e" * 64,
    )
    payload = spec.to_mapping()

    assert payload["source"]["request"]["retrieval_mode"] == "node_id"
    request_source = payload["source"]["request"]["source"]
    assert request_source["api_dataset"] == "weather.openaq.sensor.daily"
    assert request_source["measure"] == "pm25"
    assert request_source["key_values"] == {"sensorId": 42}
    assert payload["availability"]["lag_days"] == 2
    assert payload["provenance"]["schema_sha256"] == "f" * 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda node: node["alignment"].update({"mode": "guess_from_live_exchange"}),
            "alignment mode",
        ),
        (
            lambda node: node["alignment"].pop("exchange_reference_receipt_sha256"),
            "exchange reference receipt",
        ),
        (
            lambda node: node["transform"].update({"scale": 0.0}),
            "scale",
        ),
        (
            lambda node: node["transform"].update({"alpha": float("inf")}),
            "alpha",
        ),
    ],
)
def test_market_node_compiler_rejects_non_reproducible_specs(mutation, message):
    node = deepcopy(_market_node())
    mutation(node)

    with pytest.raises(PointInTimeSeriesContractError, match=message):
        compile_canonical_node_series_spec(
            node,
            source_receipt_sha256="e" * 64,
        )


def test_catalog_node_compiler_requires_frozen_schema_receipt():
    node = {
        "contract": "abel-edge.graph-node-spec/v1",
        "node_id": "catalog:weather:pm25",
        "family": "catalog_diff_then_robust_asinh_deseason",
        "source": {
            "api_dataset": "weather.openaq.sensor.daily",
            "time_field": "date",
            "measure": "pm25",
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
        "release_receipt_sha256": "d" * 64,
    }

    with pytest.raises(PointInTimeSeriesContractError, match="schema receipt"):
        compile_canonical_node_series_spec(
            node,
            source_receipt_sha256="e" * 64,
        )


def test_compiled_node_runs_through_a_registered_generic_series_adapter(tmp_path):
    class GraphNodeAdapter:
        assume_utc_for_naive = False

        def load(self, request):
            assert request.series_spec is not None
            assert request.series_spec.series_id == "ticker:AAPL:close"
            frame = pd.DataFrame(
                {
                    "event_time": ["2024-01-01T05:00:00Z"],
                    "value": [0.25],
                }
            )
            frame.attrs["source_receipt_sha256"] = "e" * 64
            frame.attrs["series_spec_sha256"] = request.series_spec.sha256
            return frame

    register_adapter("test_graph_node", GraphNodeAdapter())
    spec = compile_canonical_node_series_spec(
        _market_node(),
        source_adapter="test_graph_node",
        source_receipt_sha256="e" * 64,
    )
    primary = tmp_path / "primary.csv"
    primary.write_text(
        "timestamp,close\n2024-01-02T00:00:00Z,10\n",
        encoding="utf-8",
    )
    context = {
        "_runtime_profile": {
            "profile": "daily",
            "target": "AAA",
            "decision_event": "bar_close",
            "execution_delay_bars": 1,
            "return_basis": "close_to_close",
        },
        "_feeds": {
            "primary": {
                "name": "primary",
                "kind": "bars",
                "adapter": "csv",
                "symbol": "AAA",
                "timeframe": "1d",
                "profile": "daily",
                "path": str(primary),
            },
            "graph_parent_01": {
                "name": "graph_parent_01",
                "kind": "point_in_time_series",
                "adapter": "test_graph_node",
                "profile": "daily",
                "series_spec": spec.to_mapping(),
            },
        },
    }

    class GraphNativeEngine(StrategyEngine):
        def compute_decisions(self, ctx):
            graph = ctx.feed("graph_parent_01").native_series()
            assert graph.index[0] == pd.Timestamp("2024-01-02T05:00:00Z")
            assert graph.iloc[0] == 0.25
            return ctx.decisions([0.0])

    output = GraphNativeEngine(context=context).compute_runtime_output()

    assert list(output.next_position) == [0.0]
