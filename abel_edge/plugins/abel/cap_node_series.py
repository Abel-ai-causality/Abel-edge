"""Freeze and materialize CAP-owned scalar canonical-node series."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from abel_edge.engine.point_in_time_series import PointInTimeSeriesSpec
from abel_edge.plugins.abel._canonical_node_values import (
    CanonicalValueError,
    digest,
    finite_float,
)
from abel_edge.plugins.abel.canonical_node import compile_cap_node_series_spec
from abel_edge.plugins.abel.prices import fetch_node_series


class CanonicalNodeDataError(CanonicalValueError):
    """Raised when a frozen canonical node cannot be reproduced."""


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
    receipt = cap_node_series_receipt(rows, node_id=node_id)
    return compile_cap_node_series_spec(
        node_id=node_id,
        graph_ref=graph_ref,
        source_receipt_sha256=receipt,
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
        timestamp = optional_text(row.get("timestamp"))
        event_time = optional_text(row.get("event_time")) or timestamp
        value = finite_float(row.get("value"))
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
    return digest(
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
                optional_text(row.get("event_time"))
                or optional_text(row.get("timestamp"))
                for row in records
            ],
            "timestamp": [optional_text(row.get("timestamp")) for row in records],
            "value": [float(row["value"]) for row in records],
        }
    )
    frame.attrs["source_receipt_sha256"] = actual_receipt
    frame.attrs["series_spec_sha256"] = series_spec.sha256
    return frame


def optional_text(value: Any) -> str:
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return ""
    return str(value).strip()
