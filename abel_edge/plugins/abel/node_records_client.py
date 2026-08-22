"""Pagination helpers for the CAP ``day_bar`` exact-node mode."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
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
    requested_limit = int(limit) if limit is not None else None
    if requested_limit is not None and requested_limit <= 0:
        raise ValueError("Canonical node series limit must be positive.")
    page_limit = min(requested_limit or 1_000, 1_000)
    remaining_capacity = 200_000
    rows: list[dict[str, Any]] = []
    timestamps: set[str] = set()
    for window_start, window_end in _calendar_year_windows(start, end):
        cursor_date: str | None = None
        while remaining_capacity > 0:
            payload = fetch_page(
                node_id=canonical_id,
                start=window_start,
                end=window_end,
                limit=min(page_limit, remaining_capacity),
                cursor_date=cursor_date,
                api_key=api_key,
            )
            page_rows = _scalar_series_rows(payload, node_id=canonical_id)
            for row in page_rows[:remaining_capacity]:
                timestamp = _utc_timestamp(row.get("timestamp"), label="timestamp")
                if not _timestamp_in_window(
                    timestamp,
                    start=window_start,
                    end=window_end,
                ):
                    raise ValueError(
                        f"Abel node scalar series timestamp {timestamp} is outside "
                        f"requested window {window_start}..{window_end}."
                    )
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
            remaining_capacity -= min(len(page_rows), remaining_capacity)
            page = payload.get("page")
            if not isinstance(page, dict) or not page.get("has_more"):
                break
            if remaining_capacity <= 0:
                raise ValueError("Abel node scalar series exceeded the 200000-row safety cap.")
            next_cursor = _date_cursor(page.get("max_date"))
            if cursor_date is not None and next_cursor <= _date_cursor(cursor_date):
                raise ValueError("Abel node_id date cursor did not advance.")
            cursor_date = next_cursor.isoformat()
    ordered = sorted(rows, key=lambda row: row["timestamp"])
    return ordered[-requested_limit:] if requested_limit is not None else ordered


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


def _calendar_year_windows(start: Any, end: Any) -> list[tuple[Any, Any]]:
    start_date = _request_date(start)
    end_date = _request_date(end)
    if start_date is None or end_date is None or start_date.year == end_date.year:
        return [(start, end)]
    if end_date < start_date:
        raise ValueError("Canonical node series end must not precede start.")
    windows = []
    for year in range(start_date.year, end_date.year + 1):
        window_start = start if year == start_date.year else f"{year:04d}-01-01"
        window_end = end if year == end_date.year else f"{year:04d}-12-31"
        windows.append((window_start, window_end))
    return windows


def _request_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


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


def _timestamp_in_window(value: str, *, start: Any, end: Any) -> bool:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    lower, _ = _request_bound(start, upper=False)
    upper, upper_exclusive = _request_bound(end, upper=True)
    if lower is not None and parsed < lower:
        return False
    if upper is None:
        return True
    return parsed < upper if upper_exclusive else parsed <= upper


def _request_bound(value: Any, *, upper: bool) -> tuple[datetime | None, bool]:
    if value is None:
        return None, False
    text = str(_serialize_timestamp(value) or "").strip()
    request_date = _request_date(text)
    if request_date is not None and len(text) == 10:
        bound = datetime.combine(request_date, datetime.min.time(), tzinfo=timezone.utc)
        return (bound + timedelta(days=1), True) if upper else (bound, False)
    timestamp = _utc_timestamp(value, label="window bound")
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")), False


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
