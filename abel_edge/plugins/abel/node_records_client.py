"""Pagination helpers for the CAP ``day_bar`` exact-node mode."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Callable


NODE_SERIES_MODE = "node_series"
NODE_SERIES_SHAPE = "series"


def fetch_all_node_series(
    *,
    fetch_page: Callable[..., dict[str, Any]],
    node_id: str,
    start: str | None,
    end: str | None,
    limit: int | None,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch and validate one exact CAP scalar series across cursor pages."""

    canonical_id = _node_id(node_id)
    remaining = int(limit or 200_000)
    if remaining <= 0:
        raise ValueError("Canonical node series limit must be positive.")
    rows: list[dict[str, Any]] = []
    timestamps: set[str] = set()
    cursor_date: str | None = None
    while remaining > 0:
        payload = fetch_page(
            node_id=canonical_id,
            start=start,
            end=end,
            limit=min(remaining, 1_000),
            cursor_date=cursor_date,
            api_key=api_key,
        )
        page_rows = _scalar_series_rows(payload, node_id=canonical_id)
        for row in page_rows[:remaining]:
            timestamp = _utc_timestamp(row.get("timestamp"), label="timestamp")
            if timestamp in timestamps:
                raise ValueError(
                    f"Abel node scalar series has duplicate UTC timestamp {timestamp}."
                )
            timestamps.add(timestamp)
            normalized = dict(row)
            normalized["timestamp"] = timestamp
            if normalized.get("event_time") is not None:
                normalized["event_time"] = _utc_timestamp(
                    normalized["event_time"],
                    label="event_time",
                )
            normalized["node_id"] = canonical_id
            normalized["value"] = float(normalized["value"])
            rows.append(normalized)
        consumed = min(len(page_rows), remaining)
        remaining -= consumed
        page = payload.get("page")
        if not isinstance(page, dict) or not page.get("has_more") or remaining <= 0:
            break
        next_cursor = _date_cursor(page.get("max_date"))
        if cursor_date is not None and next_cursor <= _date_cursor(cursor_date):
            raise ValueError("Abel node_id date cursor did not advance.")
        cursor_date = next_cursor.isoformat()
    return rows


def fetch_node_series_page(
    *,
    post_market: Callable[..., dict[str, Any]],
    node_id: str,
    start: str | None,
    end: str | None,
    limit: int | None,
    cursor_date: str | None,
    api_key: str,
) -> dict[str, Any]:
    """Request CAP's scalar-series shape for one exact V4 node."""

    body = {
        "node_id": _node_id(node_id),
        "shape": NODE_SERIES_SHAPE,
        "start": _serialize_timestamp(start),
        "end": _serialize_timestamp(end),
        "limit": limit,
    }
    if cursor_date is not None:
        body["cursor_date"] = cursor_date
    payload = post_market(endpoint="day_bar", body=body, api_key=api_key)
    if not isinstance(payload, dict):
        raise ValueError("Abel node_id scalar-series response must be a mapping.")
    return payload


def fetch_all_node_records(
    *,
    fetch_page: Callable[..., dict[str, Any]],
    node_id: str,
    start: str | None,
    end: str | None,
    limit: int | None,
    api_key: str,
) -> list[dict[str, Any]]:
    canonical_id = _node_id(node_id)
    remaining = int(limit or 200_000)
    if remaining <= 0:
        raise ValueError("Canonical node series limit must be positive.")
    rows: list[dict[str, Any]] = []
    cursor_id: int | None = None
    while remaining > 0:
        payload = fetch_page(
            node_id=canonical_id,
            start=start,
            end=end,
            limit=min(remaining, 1_000),
            cursor_id=cursor_id,
            api_key=api_key,
        )
        items = payload.get("data") or payload.get("result") or []
        if isinstance(items, dict):
            items = items.get("items") or items.get("bars") or []
        page_rows = [item for item in items if isinstance(item, dict)]
        rows.extend(page_rows[:remaining])
        remaining -= min(len(page_rows), remaining)
        page = payload.get("page")
        if not isinstance(page, dict) or not page.get("has_more") or remaining <= 0:
            break
        next_cursor = page.get("max_id")
        if not isinstance(next_cursor, int) or (
            cursor_id is not None and next_cursor <= cursor_id
        ):
            raise ValueError("Abel node_id cursor did not advance.")
        cursor_id = next_cursor
    return rows


def _scalar_series_rows(
    payload: dict[str, Any],
    *,
    node_id: str,
) -> list[dict[str, Any]]:
    if payload.get("mode") != NODE_SERIES_MODE:
        raise ValueError(
            "Abel node_id response is not a scalar series; "
            f"expected mode={NODE_SERIES_MODE}, observed={payload.get('mode') or '<missing>'}."
        )
    node = payload.get("node")
    if not isinstance(node, dict) or str(node.get("node_id") or "").strip() != node_id:
        raise ValueError("Abel node scalar series did not preserve the exact node_id.")
    items = payload.get("data")
    if not isinstance(items, list):
        raise ValueError("Abel node scalar series data must be a list.")
    rows = [item for item in items if isinstance(item, dict)]
    if len(rows) != len(items):
        raise ValueError("Abel node scalar series rows must be mappings.")
    for row in rows:
        if not _finite(row.get("value")):
            raise ValueError("Abel node scalar series values must be finite.")
        _utc_timestamp(row.get("timestamp"), label="timestamp")
    return rows


def fetch_node_records_page(
    *,
    post_market: Callable[..., dict[str, Any]],
    node_id: str,
    start: str | None,
    end: str | None,
    limit: int | None,
    cursor_id: int | None,
    api_key: str,
) -> dict[str, Any]:
    body = {
        "node_id": _node_id(node_id),
        "start": _serialize_timestamp(start),
        "end": _serialize_timestamp(end),
        "limit": limit,
    }
    if cursor_id is not None:
        body["cursor_id"] = cursor_id
    payload = post_market(endpoint="day_bar", body=body, api_key=api_key)
    if not isinstance(payload, dict):
        raise ValueError("Abel node_id response must be a mapping.")
    return payload


def _node_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Canonical node_id cannot be empty.")
    return normalized


def _serialize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _date_cursor(value: Any) -> date:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Abel node_id date cursor did not advance.") from exc


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _utc_timestamp(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Abel node scalar series {label} must be UTC-aware.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"Abel node scalar series {label} must be an ISO timestamp."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"Abel node scalar series {label} must be UTC-aware.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
