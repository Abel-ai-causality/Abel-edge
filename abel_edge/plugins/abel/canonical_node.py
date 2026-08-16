"""Compile Abel canonical graph nodes into the generic Edge series contract."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping

from abel_edge.engine.point_in_time_series import (
    PointInTimeSeriesContractError,
    PointInTimeSeriesSpec,
)

CANONICAL_NODE_CONTRACT = "abel-edge.graph-node-spec/v1"
MARKET_ALIGNMENT_MODE = "exchange_close_first_05:00_utc_cutoff"
CATALOG_ALIGNMENT_MODE = "source_date_plus_availability_lag_to_05:00_utc"
MARKET_NODE_FAMILY_FIELDS = {
    "ticker_daily_close_robust_asinh_return": "close",
    "ticker_daily_volume_log1p_change_robust_asinh": "volume",
}


def compile_cap_node_series_spec(
    *,
    node_id: str,
    graph_ref: Mapping[str, Any],
    source_receipt_sha256: str,
    source_adapter: str = "abel",
) -> PointInTimeSeriesSpec:
    """Compile CAP's exact-node scalar shape without graph-transform metadata."""

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
            "provenance": {"source_receipt_sha256": source_receipt_sha256},
        }
    )


def compile_canonical_node_series_spec(
    node_spec: Mapping[str, Any],
    *,
    source_receipt_sha256: str,
    source_adapter: str = "abel",
) -> PointInTimeSeriesSpec:
    """Resolve one graph-release node into a provider-neutral Edge feed spec."""

    node = _validate_node_spec(node_spec)
    alignment = node["alignment"]
    provenance = {
        "source_receipt_sha256": source_receipt_sha256,
        "transform_receipt_sha256": node["release_receipt_sha256"],
    }
    if node.get("schema_sha256"):
        provenance["schema_sha256"] = node["schema_sha256"]
    if alignment.get("exchange_reference_receipt_sha256"):
        provenance["alignment_receipt_sha256"] = alignment[
            "exchange_reference_receipt_sha256"
        ]

    return PointInTimeSeriesSpec.from_mapping(
        {
            "contract": "abel-edge.point-in-time-series/v1",
            "series_id": node["node_id"],
            "source": {
                "adapter": source_adapter,
                "request": {
                    "node_id": node["node_id"],
                    "family": node["family"],
                    "retrieval_mode": (
                        "symbol"
                        if node["family"] in MARKET_NODE_FAMILY_FIELDS
                        else "node_id"
                    ),
                    "source": deepcopy(node["source"]),
                    "alignment": deepcopy(alignment),
                },
            },
            "schema": {
                "event_time_field": "event_time",
                "value_field": "value",
            },
            "materialization": {
                "frequency": "calendar_day",
                "timezone": "UTC",
                "grid_time_utc": "05:00:00",
                "missing_policy": "none",
                "alignment_policy": "native_only",
            },
            "transforms": [
                {
                    "op": "abel_graph_release_transform",
                    "version": 1,
                    "parameters": deepcopy(node["transform"]),
                }
            ],
            "availability": {
                "mode": "calendar_days",
                "lag_days": int(alignment["availability_lag_days"]),
            },
            "provenance": provenance,
        }
    )


def _validate_node_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PointInTimeSeriesContractError("canonical node spec must be a mapping.")
    node = deepcopy(dict(value))
    if node.get("contract") != CANONICAL_NODE_CONTRACT:
        raise PointInTimeSeriesContractError(
            f"canonical node contract must be '{CANONICAL_NODE_CONTRACT}'."
        )
    for key in ("node_id", "family", "release_receipt_sha256"):
        if not str(node.get(key) or "").strip():
            raise PointInTimeSeriesContractError(
                f"canonical node spec requires non-empty '{key}'."
            )
    for key in ("source", "alignment", "transform"):
        if not isinstance(node.get(key), dict):
            raise PointInTimeSeriesContractError(
                f"canonical node spec '{key}' must be a mapping."
            )
    lag = node["alignment"].get("availability_lag_days")
    if not isinstance(lag, int) or isinstance(lag, bool) or lag < 0:
        raise PointInTimeSeriesContractError(
            "canonical node alignment availability_lag_days must be nonnegative."
        )
    mode = node["alignment"].get("mode")
    if mode not in {MARKET_ALIGNMENT_MODE, CATALOG_ALIGNMENT_MODE}:
        raise PointInTimeSeriesContractError(
            f"canonical node alignment mode '{mode}' is not supported."
        )
    if mode == MARKET_ALIGNMENT_MODE:
        _require_nonempty(node["source"], ("api_dataset", "field", "symbol"), scope="source")
        _require_nonempty(
            node["alignment"],
            ("exchange", "timezone", "exchange_reference_receipt_sha256"),
            scope="alignment",
            label_overrides={
                "exchange_reference_receipt_sha256": "exchange reference receipt",
            },
        )
        expected_field = MARKET_NODE_FAMILY_FIELDS.get(node["family"])
        if expected_field is None or node["source"]["field"] != expected_field:
            raise PointInTimeSeriesContractError(
                "canonical market family must be a registered close/volume "
                "family whose source field matches the family."
            )
    else:
        _require_nonempty(
            node["source"],
            ("api_dataset", "time_field", "measure"),
            scope="source",
        )
        _require_nonempty(node["alignment"], ("time_policy",), scope="alignment")
        if not str(node.get("schema_sha256") or "").strip():
            raise PointInTimeSeriesContractError(
                "canonical catalog node requires a frozen schema receipt."
            )
    _validate_transform(node["transform"])
    return node


def _validate_transform(transform: dict[str, Any]) -> None:
    if transform.get("kind") not in {"log_return", "diff_log1p", "diff"}:
        raise PointInTimeSeriesContractError(
            f"canonical node transform kind '{transform.get('kind')}' is not supported."
        )
    for key in ("alpha", "scale"):
        value = transform.get(key)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise PointInTimeSeriesContractError(
                f"canonical node transform {key} must be finite and positive."
            )
    center = transform.get("center")
    if (
        not isinstance(center, (int, float))
        or isinstance(center, bool)
        or not math.isfinite(float(center))
    ):
        raise PointInTimeSeriesContractError(
            "canonical node transform center must be finite."
        )
    weekday_index = transform.get("weekday_centers_index")
    if weekday_index is not None and (
        not isinstance(weekday_index, int)
        or isinstance(weekday_index, bool)
        or weekday_index < 0
    ):
        raise PointInTimeSeriesContractError(
            "canonical node weekday_centers_index must be a nonnegative integer or null."
        )
    weekday_centers = transform.get("weekday_centers")
    if weekday_index is not None and (
        not isinstance(weekday_centers, list)
        or len(weekday_centers) != 7
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            for value in weekday_centers
        )
    ):
        raise PointInTimeSeriesContractError(
            "canonical node transform with weekday_centers_index requires "
            "seven finite weekday_centers."
        )


def _require_nonempty(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    *,
    scope: str,
    label_overrides: dict[str, str] | None = None,
) -> None:
    for key in keys:
        if not str(payload.get(key) or "").strip():
            label = (label_overrides or {}).get(key, f"{scope}.{key}")
            raise PointInTimeSeriesContractError(
                f"canonical node requires non-empty {label}."
            )
