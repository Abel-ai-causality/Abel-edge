"""Pagination helpers for the CAP ``day_bar`` exact-node mode."""

from __future__ import annotations

from typing import Any, Callable


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
