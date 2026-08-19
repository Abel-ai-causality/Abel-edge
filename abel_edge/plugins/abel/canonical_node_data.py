"""Materialize Abel canonical graph nodes through the built-in Abel adapter."""

from __future__ import annotations

import math
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from abel_edge.engine.point_in_time_series import PointInTimeSeriesSpec
from abel_edge.plugins.abel._canonical_node_values import (
    align_market_day,
    digest,
    finite_float,
    parse_date,
    required_date,
    series_receipt,
)
from abel_edge.plugins.abel.credentials import require_api_key
from abel_edge.plugins.abel.canonical_node import (
    MARKET_NODE_FAMILY_FIELDS,
)
from abel_edge.plugins.abel.cap_node_series import (
    CanonicalNodeDataError,
    cap_node_series_receipt as cap_node_series_receipt,
    materialize_cap_node_series as _materialize_cap_node_series,
    prepare_cap_node_series_spec as prepare_cap_node_series_spec,
)
from abel_edge.plugins.abel.canonical_source_window import (
    filter_visible_frame,
    resolve_materialization_window,
)
from abel_edge.plugins.abel.prices import fetch_bars, fetch_node_series

DEFAULT_DATA_BASE_URL = "https://cap.abel.ai/data-infra"


def load_canonical_node_series(
    *,
    series_spec: PointInTimeSeriesSpec,
    start,
    end,
    limit: int | None,
    config: dict | None,
) -> pd.DataFrame:
    """Fetch, transform, and receipt-check one canonical graph-node series."""

    payload = series_spec.payload
    options = config or {}
    if series_spec.source_adapter != "abel":
        raise CanonicalNodeDataError(
            "Abel canonical materialization requires source.adapter='abel'."
        )
    request = payload["source"]["request"]
    node_id = str(request["node_id"])
    retrieval_mode = str(request.get("retrieval_mode") or "")
    (
        source_start,
        source_end,
        source_limit,
        visible_start,
        visible_end,
    ) = resolve_materialization_window(
        start=start,
        end=end,
        limit=limit,
        config=options,
        availability_lag_days=int(payload["availability"].get("lag_days", 0)),
    )

    if retrieval_mode == "node_series":
        frame = _materialize_cap_node_series(
            series_spec=series_spec,
            node_id=node_id,
            start=source_start,
            end=source_end,
            limit=source_limit,
            config=options,
        )
        return filter_visible_frame(
            frame,
            start=visible_start,
            end=visible_end,
            limit=limit,
        )

    family = str(request["family"])
    source = request["source"]
    alignment = request["alignment"]
    transform = payload["transforms"][0]["parameters"]

    expected_mode = (
        "symbol" if family in MARKET_NODE_FAMILY_FIELDS else "node_id"
    )
    if retrieval_mode != expected_mode:
        raise CanonicalNodeDataError(
            "Canonical node retrieval_mode does not match its family: "
            f"expected {expected_mode}, got {retrieval_mode or '<missing>'}."
        )

    if retrieval_mode == "symbol":
        raw_series, transformed = _materialize_market(
            source=source,
            alignment=alignment,
            transform=transform,
            start=source_start,
            end=source_end,
            limit=source_limit,
            config=options,
            expected_alignment_receipt=payload["provenance"].get(
                "alignment_receipt_sha256"
            ),
        )
    else:
        raw_series, transformed = _materialize_catalog(
            node_id=node_id,
            source=source,
            alignment=alignment,
            transform=transform,
            start=source_start,
            end=source_end,
            limit=source_limit,
            config=options,
        )

    visible_start_date = required_date(visible_start, label="start")
    visible_end_date = required_date(visible_end, label="end")
    availability_lag = int(payload["availability"].get("lag_days", 0))
    transformed = {
        event_day: value
        for event_day, value in transformed.items()
        if visible_start_date
        <= event_day + timedelta(days=availability_lag)
        <= visible_end_date
    }
    if limit is not None:
        transformed = dict(list(transformed.items())[-int(limit) :])
    actual_receipt = series_receipt(raw_series)
    expected_receipt = payload["provenance"]["source_receipt_sha256"]
    if actual_receipt != expected_receipt:
        raise CanonicalNodeDataError(
            "Canonical node source receipt drift: "
            f"expected {expected_receipt}, got {actual_receipt}."
        )
    frame = pd.DataFrame(
        {
            "event_time": [
                pd.Timestamp(
                    datetime.combine(day, time(5, 0), tzinfo=timezone.utc)
                )
                for day in transformed
            ],
            "value": [transformed[day] for day in transformed],
        }
    )
    frame.attrs["source_receipt_sha256"] = actual_receipt
    frame.attrs["series_spec_sha256"] = series_spec.sha256
    return frame


def _materialize_market(
    *,
    source: dict[str, Any],
    alignment: dict[str, Any],
    transform: dict[str, Any],
    start,
    end,
    limit: int | None,
    config: dict[str, Any],
    expected_alignment_receipt: str | None,
) -> tuple[dict[date, float], dict[date, float]]:
    symbol = str(source["symbol"])
    field = str(source["field"])
    rows = fetch_bars(
        symbols=[symbol],
        start=start,
        end=end,
        timeframe="1d",
        limit=limit or 200_000,
        fields=[field],
        config=config,
    )
    raw_series: dict[date, float] = {}
    for row in rows.to_dict("records"):
        if str(row.get("symbol") or symbol).strip() != symbol:
            continue
        source_day = parse_date(row.get("timestamp"))
        value = finite_float(row.get(field))
        if source_day is not None and value is not None:
            raw_series[source_day] = value

    exchange_rows = _fetch_exchange_reference(config=config)
    actual_alignment_receipt = digest(exchange_rows)
    if (
        expected_alignment_receipt
        and actual_alignment_receipt != expected_alignment_receipt
    ):
        raise CanonicalNodeDataError(
            "Canonical exchange-reference receipt drift: "
            f"expected {expected_alignment_receipt}, "
            f"got {actual_alignment_receipt}."
        )
    reference = {
        str(row.get("exchange") or "").upper(): row for row in exchange_rows
    }
    aligned: dict[date, float] = {}
    for source_day, value in sorted(raw_series.items()):
        event_day = align_market_day(
            source_day,
            exchange=str(alignment["exchange"]),
            timezone_name=str(alignment["timezone"]),
            exchange_reference=reference,
        )
        aligned[event_day] = value
    transformed = _transform_levels(
        aligned,
        transform=transform,
        weekday_lag_days=0,
    )
    return raw_series, transformed


def _materialize_catalog(
    *,
    node_id: str,
    source: dict[str, Any],
    alignment: dict[str, Any],
    transform: dict[str, Any],
    start,
    end,
    limit: int | None,
    config: dict[str, Any],
) -> tuple[dict[date, float], dict[date, float]]:
    rows = fetch_node_series(
        node_id=node_id,
        start=start,
        end=end,
        limit=limit or 200_000,
        config=config,
    )
    raw_series = _raw_node_values(
        rows,
        node_id=node_id,
        value_fields=(
            "value",
            str(source.get("measure_field") or ""),
            str(source.get("measure") or ""),
        ),
    )
    transformed = _transform_levels(
        raw_series,
        transform=transform,
        weekday_lag_days=int(alignment["availability_lag_days"]),
    )
    return raw_series, transformed


def _raw_node_values(
    rows: pd.DataFrame,
    *,
    node_id: str,
    value_fields: tuple[str, ...],
) -> dict[date, float]:
    """Normalize the raw UTC rows returned by day_bar node_id mode."""

    raw_series: dict[date, float] = {}
    for row in rows.to_dict("records"):
        returned_node = str(row.get("node_id") or "").strip()
        if returned_node and returned_node != node_id:
            raise CanonicalNodeDataError(
                "Canonical node response contains unexpected node_id "
                f"'{returned_node}' for '{node_id}'."
            )
        source_day = parse_date(
            row.get("timestamp")
            or row.get("event_time")
            or row.get("date")
        )
        value = None
        for field in value_fields:
            if field:
                value = finite_float(row.get(field))
                if value is not None:
                    break
        if source_day is None or value is None:
            continue
        if source_day in raw_series:
            raise CanonicalNodeDataError(
                f"Canonical node response has duplicate UTC day {source_day}."
            )
        raw_series[source_day] = value
    return raw_series


def _transform_levels(
    levels: dict[date, float],
    *,
    transform: dict[str, Any],
    weekday_lag_days: int,
) -> dict[date, float]:
    centers = transform.get("weekday_centers")
    if transform.get("weekday_centers_index") is not None:
        if not isinstance(centers, list) or len(centers) != 7:
            raise CanonicalNodeDataError(
                "Canonical transform requires seven frozen weekday_centers."
            )
    else:
        centers = [0.0] * 7
    transformed: dict[date, float] = {}
    previous: float | None = None
    for source_day, level in sorted(levels.items()):
        if previous is None:
            previous = level
            continue
        kind = transform["kind"]
        if kind == "log_return":
            base = (
                math.log(level / previous)
                if level > 0 and previous > 0
                else math.nan
            )
        elif kind == "diff_log1p":
            base = (
                math.log1p(level) - math.log1p(previous)
                if level >= 0 and previous >= 0
                else math.nan
            )
        else:
            base = level - previous
        previous = level
        if not math.isfinite(base):
            continue
        weekday_day = source_day + timedelta(days=weekday_lag_days)
        weekday = float(centers[weekday_day.weekday()])
        value = math.asinh(
            (
                base
                - weekday
                - float(transform["center"])
            )
            / (float(transform["alpha"]) * float(transform["scale"]))
        )
        transformed[source_day] = value
    return transformed


def _fetch_exchange_reference(*, config: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _data_get(
        "api/data-tasks/market.reference.exchanges/records",
        params={"limit": 200},
        config=config,
    )
    return list((payload.get("data") or {}).get("records") or [])


def _data_get(
    path: str,
    *,
    params: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    token = require_api_key(env_path=config.get("env_path", ".env"))
    base = str(
        config.get("data_base_url")
        or os.getenv("ABEL_DATA_BASE_URL")
        or DEFAULT_DATA_BASE_URL
    ).rstrip("/")
    response = requests.get(
        f"{base}/{path.lstrip('/')}",
        headers={
            "Accept": "application/json",
            "Authorization": token
            if token.lower().startswith("bearer ")
            else f"Bearer {token}",
        },
        params=params,
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success", True):
        raise CanonicalNodeDataError(
            str(payload.get("msg") or "Abel Data API request failed.")
        )
    return payload
