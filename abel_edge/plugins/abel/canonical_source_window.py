"""Frozen-source replay and runtime visibility windows for canonical series."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from abel_edge.plugins.abel._canonical_node_values import required_date
from abel_edge.plugins.abel.cap_node_series import CanonicalNodeDataError


def resolve_materialization_window(
    *,
    start,
    end,
    limit: int | None,
    config: dict[str, Any],
    availability_lag_days: int = 0,
) -> tuple[Any, Any, int | None, Any, Any]:
    """Separate the frozen receipt window from the runtime-visible window."""

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
    if availability_lag_days < 0:
        raise CanonicalNodeDataError(
            "Canonical availability_lag_days must be nonnegative."
        )
    source_start = frozen_start if frozen_start is not None else visible_start
    source_end = frozen_end if frozen_end is not None else visible_end
    if frozen_start is None and availability_lag_days:
        source_start = (
            required_date(visible_start, label="start")
            - timedelta(days=availability_lag_days)
        ).isoformat()
    source_start_date = required_date(source_start, label="source_start")
    source_end_date = required_date(source_end, label="source_end")
    visible_start_date = required_date(visible_start, label="start")
    visible_end_date = required_date(visible_end, label="end")
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
    elif availability_lag_days:
        source_limit = None
    return source_start, source_end, source_limit, visible_start, visible_end


def filter_visible_frame(
    frame: pd.DataFrame,
    *,
    start,
    end,
    limit: int | None,
) -> pd.DataFrame:
    """Apply runtime visibility only after a frozen source receipt is verified."""

    time_field = "timestamp" if "timestamp" in frame.columns else "event_time"
    timestamps = pd.to_datetime(frame[time_field], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise CanonicalNodeDataError(
            f"Canonical node series has invalid UTC {time_field} values."
        )
    start_date = required_date(start, label="start")
    end_date = required_date(end, label="end")
    visible = frame[
        (timestamps.dt.date >= start_date) & (timestamps.dt.date <= end_date)
    ].copy()
    if limit is not None:
        visible = visible.tail(int(limit)).copy()
    visible.attrs.update(frame.attrs)
    result = visible.reset_index(drop=True)
    result.attrs.update(frame.attrs)
    return result
