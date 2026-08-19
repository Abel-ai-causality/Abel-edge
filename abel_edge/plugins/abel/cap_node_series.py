"""Compile, freeze, and materialize CAP-owned scalar node series."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from typing import Any, Callable, Mapping

import pandas as pd

from abel_edge.engine.feed_contract import FeedContractError
from abel_edge.engine.point_in_time_series import (
    PointInTimeSeriesContractError,
    PointInTimeSeriesSpec,
)
from abel_edge.plugins.abel.prices import fetch_node_series


class CanonicalNodeDataError(FeedContractError):
    """Raised when a frozen CAP scalar node cannot be reproduced."""


def compile_cap_node_series_spec(
    *,
    node_id: str,
    graph_ref: Mapping[str, Any],
    source_receipt_sha256: str,
    source_adapter: str = "abel",
    source_observation_count: int | None = None,
    source_first_timestamp: str | None = None,
    source_last_timestamp: str | None = None,
) -> PointInTimeSeriesSpec:
    """Compile CAP's exact-node scalar shape into the generic Edge contract."""

    canonical_id = str(node_id or "").strip()
    if not canonical_id:
        raise PointInTimeSeriesContractError("CAP node_id must be non-empty.")
    frozen_graph_ref = {
        "graph_id": str(graph_ref.get("graph_id") or "").strip(),
        "graph_version": str(graph_ref.get("graph_version") or "").strip(),
    }
    if not all(frozen_graph_ref.values()):
        raise PointInTimeSeriesContractError(
            "CAP node series requires graph_id and graph_version."
        )
    provenance: dict[str, Any] = {
        "source_receipt_sha256": source_receipt_sha256,
    }
    if source_observation_count is not None:
        provenance["source_observation_count"] = int(source_observation_count)
    if source_first_timestamp is not None:
        provenance["source_first_timestamp"] = str(source_first_timestamp)
    if source_last_timestamp is not None:
        provenance["source_last_timestamp"] = str(source_last_timestamp)
    return PointInTimeSeriesSpec.from_mapping(
        {
            "contract": "abel-edge.point-in-time-series/v1",
            "series_id": canonical_id,
            "source": {
                "adapter": source_adapter,
                "request": {
                    "node_id": canonical_id,
                    "retrieval_mode": "node_series",
                    "graph_ref": frozen_graph_ref,
                },
            },
            "schema": {
                "event_time_field": "event_time",
                "available_at_field": "timestamp",
                "value_field": "value",
            },
            "materialization": {
                "frequency": "irregular",
                "timezone": "UTC",
                "missing_policy": "none",
                "alignment_policy": "asof",
            },
            "transforms": [],
            "availability": {"mode": "explicit"},
            "provenance": provenance,
        }
    )


def prepare_cap_node_series_spec(
    *,
    node_id: str,
    graph_ref: dict[str, Any],
    start,
    end,
    limit: int | None = None,
    config: dict | None = None,
    fetcher: Callable[..., pd.DataFrame] | None = None,
) -> PointInTimeSeriesSpec:
    """Probe one live CAP scalar series and freeze its response receipt."""

    rows = (fetcher or fetch_node_series)(
        node_id=node_id,
        start=start,
        end=end,
        limit=limit,
        config=config or {},
    )
    records = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else list(rows)
    if not records:
        raise CanonicalNodeDataError(
            f"CAP node scalar series returned no observations: {node_id}"
        )
    receipt = cap_node_series_receipt(rows, node_id=node_id)
    timestamps = sorted(_optional_text(row.get("timestamp")) for row in records)
    return compile_cap_node_series_spec(
        node_id=node_id,
        graph_ref=graph_ref,
        source_receipt_sha256=receipt,
        source_observation_count=len(records),
        source_first_timestamp=timestamps[0],
        source_last_timestamp=timestamps[-1],
    )


def load_cap_node_series(
    *,
    series_spec: PointInTimeSeriesSpec,
    start,
    end,
    limit: int | None,
    config: dict | None,
) -> pd.DataFrame:
    """Replay the frozen CAP source window, verify it, then filter visibility."""

    if series_spec.source_adapter != "abel":
        raise CanonicalNodeDataError(
            "CAP scalar-node materialization requires source.adapter='abel'."
        )
    request = series_spec.source_request
    if request.get("retrieval_mode") != "node_series":
        raise CanonicalNodeDataError(
            "CAP scalar-node materialization requires retrieval_mode='node_series'."
        )
    source_start, source_end, source_limit, visible_start, visible_end = (
        _materialization_window(
            start=start,
            end=end,
            limit=limit,
            config=config or {},
        )
    )
    frame = materialize_cap_node_series(
        series_spec=series_spec,
        node_id=str(request["node_id"]),
        start=source_start,
        end=source_end,
        limit=source_limit,
        config=config or {},
    )
    return _filter_visible_frame(
        frame,
        start=visible_start,
        end=visible_end,
        limit=limit,
    )


def cap_node_series_receipt(rows, *, node_id: str) -> str:
    """Hash the exact normalized scalar observations for one CAP node."""

    records = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else list(rows)
    canonical_id = str(node_id or "").strip()
    normalized = []
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            raise CanonicalNodeDataError("CAP node scalar-series rows must be mappings.")
        returned = str(row.get("node_id") or canonical_id).strip()
        if returned != canonical_id:
            raise CanonicalNodeDataError(
                f"Canonical node response contains unexpected node_id '{returned}' "
                f"for '{canonical_id}'."
            )
        timestamp = _optional_text(row.get("timestamp"))
        event_time = _optional_text(row.get("event_time")) or timestamp
        value = _finite_float(row.get("value"))
        if not timestamp or not event_time or value is None:
            raise CanonicalNodeDataError(
                "CAP node scalar series requires timestamp, event_time, and finite value."
            )
        if timestamp in seen:
            raise CanonicalNodeDataError(
                f"CAP node scalar series has duplicate UTC timestamp {timestamp}."
            )
        seen.add(timestamp)
        normalized.append(
            {
                "event_time": event_time,
                "timestamp": timestamp,
                "value": format(value, ".17g"),
            }
        )
    return _digest(
        {
            "node_id": canonical_id,
            "rows": sorted(normalized, key=lambda row: row["timestamp"]),
        }
    )


def materialize_cap_node_series(
    *,
    series_spec: PointInTimeSeriesSpec,
    node_id: str,
    start,
    end,
    limit: int | None,
    config: dict[str, Any],
    fetcher: Callable[..., pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Fetch and receipt-check one bounded CAP scalar series."""

    rows = (fetcher or fetch_node_series)(
        node_id=node_id,
        start=start,
        end=end,
        limit=limit,
        config=config,
    )
    records = rows.to_dict("records")
    actual_receipt = cap_node_series_receipt(records, node_id=node_id)
    expected_receipt = series_spec.payload["provenance"]["source_receipt_sha256"]
    if actual_receipt != expected_receipt:
        raise CanonicalNodeDataError(
            "Canonical node source receipt drift: "
            f"expected {expected_receipt}, got {actual_receipt}."
        )
    frame = pd.DataFrame(
        {
            "event_time": [
                _optional_text(row.get("event_time"))
                or _optional_text(row.get("timestamp"))
                for row in records
            ],
            "timestamp": [_optional_text(row.get("timestamp")) for row in records],
            "value": [float(row["value"]) for row in records],
        }
    )
    frame.attrs["source_receipt_sha256"] = actual_receipt
    frame.attrs["series_spec_sha256"] = series_spec.sha256
    return frame


def _materialization_window(
    *,
    start,
    end,
    limit: int | None,
    config: dict[str, Any],
) -> tuple[Any, Any, int | None, Any, Any]:
    frozen_start = config.get("source_start")
    frozen_end = config.get("source_end")
    if (frozen_start is None) != (frozen_end is None):
        raise CanonicalNodeDataError(
            "Frozen canonical source receipts require source_start and source_end together."
        )
    visible_start = start if start is not None else frozen_start
    visible_end = end if end is not None else frozen_end
    if visible_start is None or visible_end is None:
        raise CanonicalNodeDataError(
            "Frozen canonical source receipts require explicit start and end dates."
        )
    source_start = frozen_start if frozen_start is not None else visible_start
    source_end = frozen_end if frozen_end is not None else visible_end
    source_start_date = _required_date(source_start, label="source_start")
    source_end_date = _required_date(source_end, label="source_end")
    visible_start_date = _required_date(visible_start, label="start")
    visible_end_date = _required_date(visible_end, label="end")
    if source_start_date > source_end_date:
        raise CanonicalNodeDataError("Canonical source_start must not exceed source_end.")
    if visible_start_date > visible_end_date:
        raise CanonicalNodeDataError("Canonical visible start must not exceed end.")
    if visible_start_date < source_start_date or visible_end_date > source_end_date:
        raise CanonicalNodeDataError(
            "Canonical visible window must stay within the frozen source window."
        )
    source_limit = limit
    if frozen_start is not None:
        raw_source_limit = config.get("source_limit")
        source_limit = int(raw_source_limit) if raw_source_limit is not None else None
    return source_start, source_end, source_limit, visible_start, visible_end


def _filter_visible_frame(
    frame: pd.DataFrame,
    *,
    start,
    end,
    limit: int | None,
) -> pd.DataFrame:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CanonicalNodeDataError(
            "Canonical node series has invalid UTC timestamp values."
        )
    start_date = _required_date(start, label="start")
    end_date = _required_date(end, label="end")
    visible = frame[
        (timestamps.dt.date >= start_date) & (timestamps.dt.date <= end_date)
    ].copy()
    if limit is not None:
        visible = visible.tail(int(limit)).copy()
    visible.attrs.update(frame.attrs)
    result = visible.reset_index(drop=True)
    result.attrs.update(frame.attrs)
    return result


def _optional_text(value: Any) -> str:
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return ""
    return str(value).strip()


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_date(value: Any, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise CanonicalNodeDataError(
            f"Canonical source {label} must be an ISO date."
        ) from exc
