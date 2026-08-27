"""Runtime and configuration tests for point-in-time auxiliary series."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from abel_edge.config import load_config
from abel_edge.engine.adapter_registry import AdapterRegistryError, register_adapter
from abel_edge.engine.base import StrategyEngine
from abel_edge.engine.feed_contract import FeedAlignmentError, FeedDateGuardError
from abel_edge.engine.feed_loader import load_feed_frame
from abel_edge.engine.point_in_time_series import (
    PointInTimeSeriesContractError,
)
from abel_edge.engine.runtime_contract import DecisionContractError


def _series_spec(*, path: str = "macro.csv") -> dict:
    source_receipt = "a" * 64
    source_path = Path(path)
    if source_path.is_file():
        source_receipt = hashlib.sha256(source_path.read_bytes()).hexdigest()
    return {
        "contract": "abel-edge.point-in-time-series/v1",
        "series_id": "macro.cpi.us",
        "source": {
            "adapter": "csv",
            "request": {"path": path},
        },
        "schema": {
            "event_time_field": "observed_at",
            "available_at_field": "released_at",
            "value_field": "reading",
        },
        "materialization": {
            "frequency": "irregular",
            "timezone": "UTC",
            "missing_policy": "none",
            "alignment_policy": "asof",
        },
        "transforms": [],
        "availability": {"mode": "explicit"},
        "provenance": {
            "source_receipt_sha256": source_receipt,
            "schema_sha256": "b" * 64,
        },
    }


def test_config_and_decision_context_support_point_in_time_series(tmp_path):
    primary = tmp_path / "primary.csv"
    primary.write_text(
        "timestamp,close\n"
        "2024-01-02T00:00:00Z,10\n"
        "2024-01-03T00:00:00Z,11\n",
        encoding="utf-8",
    )
    macro = tmp_path / "macro.csv"
    macro.write_text(
        "observed_at,released_at,reading\n"
        "2024-01-01T00:00:00Z,2024-01-02T05:00:00Z,100\n"
        "2024-01-02T00:00:00Z,2024-01-03T05:00:00Z,101\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "strategies.yaml"
    spec = _series_spec(path=str(macro).replace("\\", "/"))
    primary_path = str(primary).replace("\\", "/")
    config_path.write_text(
        f"""
settings: {{}}
strategies:
  - id: demo
    name: Demo
    asset: AAA
    color: "#2563EB"
    engine: strategies.demo.engine
    trade_log: data/demo.csv
    price_data:
      adapter: csv
      path: {primary_path}
    feeds:
      macro:
        kind: point_in_time_series
        series_spec: {spec!r}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    context = load_config(config_path)["strategies"][0]

    class PointInTimeEngine(StrategyEngine):
        def compute_decisions(self, ctx):
            native = ctx.feed("macro").native_series()
            assert list(native.index) == [
                pd.Timestamp("2024-01-02T05:00:00Z"),
                pd.Timestamp("2024-01-03T05:00:00Z"),
            ]
            aligned = ctx.feed("macro").asof_series()
            assert pd.isna(aligned.iloc[0])
            assert aligned.iloc[1] == 100.0
            return ctx.decisions([0.0, 0.0])

    compiled = PointInTimeEngine(context=context).compute_runtime_output()

    assert list(compiled.next_position) == [0.0, 0.0]
    feed = context["_feeds"]["macro"]
    assert feed["adapter"] == "csv"
    assert feed["series_spec"]["series_id"] == "macro.cpi.us"


def test_csv_point_in_time_rejects_unapplied_transforms(tmp_path):
    data_path = tmp_path / "macro.csv"
    data_path.write_text(
        "observed_at,released_at,reading\n"
        "2024-01-01T00:00:00Z,2024-01-02T05:00:00Z,100\n",
        encoding="utf-8",
    )
    spec = _series_spec(path=str(data_path).replace("\\", "/"))
    spec["transforms"] = [{"op": "scale", "parameters": {"factor": 2.0}}]

    with pytest.raises(AdapterRegistryError, match="does not support series_spec.transforms"):
        load_feed_frame(
            {
                "name": "macro",
                "kind": "point_in_time_series",
                "adapter": "csv",
                "profile": "daily",
                "series_spec": spec,
            }
        )


def test_legacy_series_config_remains_supported(tmp_path):
    series_path = tmp_path / "series.csv"
    series_path.write_text(
        "timestamp,reading\n2024-01-01T00:00:00Z,1\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "strategies.yaml"
    series_file = str(series_path).replace("\\", "/")
    config_path.write_text(
        f"""
settings: {{}}
strategies:
  - id: demo
    name: Demo
    asset: AAA
    color: "#2563EB"
    engine: strategies.demo.engine
    trade_log: data/demo.csv
    feeds:
      legacy:
        kind: series
        adapter: csv
        field: reading
        path: {series_file}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    feed = load_config(config_path)["strategies"][0]["_feeds"]["legacy"]

    assert feed["kind"] == "series"
    assert feed["field"] == "reading"


def test_date_guard_uses_available_at_instead_of_event_time(tmp_path, monkeypatch):
    data_path = tmp_path / "macro.csv"
    data_path.write_text(
        "observed_at,released_at,reading\n"
        "2024-01-01T00:00:00Z,2024-01-03T05:00:00Z,1\n",
        encoding="utf-8",
    )
    spec = _series_spec(path=str(data_path).replace("\\", "/"))
    monkeypatch.setenv("ABEL_EDGE_MAX_DATA_DATE", "2024-01-02")
    monkeypatch.setenv("ABEL_EDGE_DATE_GUARD_MODE", "fail-closed")

    with pytest.raises(FeedDateGuardError, match="polluted_cache"):
        load_feed_frame(
            {
                "name": "macro",
                "kind": "point_in_time_series",
                "adapter": "csv",
                "profile": "daily",
                "series_spec": spec,
            }
        )


def test_point_in_time_feed_uses_frozen_source_end_before_global_cutoff(monkeypatch):
    calls = []

    class RecordingPointInTimeAdapter:
        assume_utc_for_naive = False

        def load(self, request):
            calls.append(request)
            frame = pd.DataFrame(
                {
                    "observed_at": ["2025-06-28T00:00:00Z"],
                    "released_at": ["2025-06-29T00:00:00Z"],
                    "reading": [1.0],
                }
            )
            frame.attrs["source_receipt_sha256"] = request.series_spec.payload[
                "provenance"
            ]["source_receipt_sha256"]
            frame.attrs["series_spec_sha256"] = request.series_spec.sha256
            return frame

    register_adapter("recording_point_in_time", RecordingPointInTimeAdapter())
    spec = _series_spec()
    spec["source"]["adapter"] = "recording_point_in_time"
    monkeypatch.setenv("ABEL_EDGE_MAX_DATA_DATE", "2025-06-30")
    monkeypatch.setenv("ABEL_EDGE_DATE_GUARD_MODE", "fail-closed")

    load_feed_frame(
        {
            "name": "canonical",
            "kind": "point_in_time_series",
            "adapter": "recording_point_in_time",
            "profile": "daily",
            "series_spec": spec,
            "source_start": "2020-01-01",
            "source_end": "2025-06-29",
        }
    )

    assert calls[0].end == "2025-06-29"
    assert calls[0].options["source_end"] == "2025-06-29"


def test_loader_rejects_adapter_source_receipt_drift():
    class StaleReceiptAdapter:
        assume_utc_for_naive = False

        def load(self, request):
            frame = pd.DataFrame(
                {
                    "observed_at": ["2024-01-01T00:00:00Z"],
                    "released_at": ["2024-01-02T05:00:00Z"],
                    "reading": [1.0],
                }
            )
            frame.attrs["source_receipt_sha256"] = "c" * 64
            return frame

    register_adapter("stale_receipt", StaleReceiptAdapter())
    spec = _series_spec()
    spec["source"]["adapter"] = "stale_receipt"

    with pytest.raises(PointInTimeSeriesContractError, match="source receipt"):
        load_feed_frame(
            {
                "name": "macro",
                "kind": "point_in_time_series",
                "adapter": "stale_receipt",
                "profile": "daily",
                "series_spec": spec,
            }
        )


def test_loader_rejects_adapter_materialized_under_another_spec():
    class WrongSpecAdapter:
        assume_utc_for_naive = False

        def load(self, request):
            frame = pd.DataFrame(
                {
                    "observed_at": ["2024-01-01T00:00:00Z"],
                    "released_at": ["2024-01-02T05:00:00Z"],
                    "reading": [1.0],
                }
            )
            frame.attrs["source_receipt_sha256"] = "a" * 64
            frame.attrs["series_spec_sha256"] = "c" * 64
            return frame

    register_adapter("wrong_spec", WrongSpecAdapter())
    spec = _series_spec()
    spec["source"]["adapter"] = "wrong_spec"

    with pytest.raises(PointInTimeSeriesContractError, match="spec identity"):
        load_feed_frame(
            {
                "name": "macro",
                "kind": "point_in_time_series",
                "adapter": "wrong_spec",
                "profile": "daily",
                "series_spec": spec,
            }
        )


def test_native_only_point_in_time_feed_rejects_asof_access(tmp_path):
    primary = tmp_path / "primary.csv"
    primary.write_text(
        "timestamp,close\n2024-01-02T00:00:00Z,10\n",
        encoding="utf-8",
    )
    driver = tmp_path / "driver.csv"
    driver.write_text(
        "observed_at,released_at,reading\n"
        "2024-01-01T05:00:00Z,2024-01-01T05:00:00Z,1\n",
        encoding="utf-8",
    )
    spec = _series_spec(path=str(driver).replace("\\", "/"))
    spec["materialization"]["alignment_policy"] = "native_only"
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
            "driver": {
                "name": "driver",
                "kind": "point_in_time_series",
                "adapter": "csv",
                "profile": "daily",
                "series_spec": spec,
            },
        },
    }

    class UnsafeAlignmentEngine(StrategyEngine):
        def compute_decisions(self, ctx):
            ctx.feed("driver").asof_series()
            return ctx.decisions([0.0])

    with pytest.raises(DecisionContractError, match="native_only"):
        UnsafeAlignmentEngine(context=context).compute_runtime_output()

    class UnsafePointAsOfEngine(StrategyEngine):
        def compute_decisions(self, ctx):
            for point in ctx.points():
                point.feed("driver").asof()
            return ctx.decisions([0.0])

    with pytest.raises(DecisionContractError, match="native_only"):
        UnsafePointAsOfEngine(context=context).compute_runtime_output()

    raw_engine = UnsafeAlignmentEngine(context=context)
    with pytest.raises(FeedAlignmentError, match="native_only"):
        raw_engine.feed_series(
            "driver",
            align_to=pd.DatetimeIndex(["2024-01-02T00:00:00Z"]),
        )

    class LegacyUnsafeEngine(StrategyEngine):
        def compute_signals(self):
            raise AssertionError("native-only feeds must be rejected before legacy execution")

    with pytest.raises(DecisionContractError, match="compute_decisions"):
        LegacyUnsafeEngine(context=context).compute_runtime_output()
