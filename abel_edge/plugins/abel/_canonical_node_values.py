"""Value, timestamp, and receipt helpers for canonical Abel nodes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from abel_edge.engine.feed_contract import FeedContractError


class CanonicalValueError(FeedContractError):
    """Raised when canonical source values cannot be interpreted safely."""


def align_market_day(
    source_day: date,
    *,
    exchange: str,
    timezone_name: str,
    exchange_reference: dict[str, dict[str, Any]],
) -> date:
    if exchange.upper() == "CRYPTO":
        closing = time(23, 59)
    else:
        row = exchange_reference.get(exchange.upper())
        if row is None:
            raise CanonicalValueError(
                f"Canonical exchange reference is missing {exchange}."
            )
        closing = parse_closing_time(row.get("closingHour"))
    local = datetime.combine(
        source_day,
        closing,
        tzinfo=ZoneInfo(timezone_name),
    )
    close_utc = local.astimezone(timezone.utc)
    cutoff = datetime.combine(
        close_utc.date(),
        time(5, 0),
        tzinfo=timezone.utc,
    )
    return (
        close_utc.date()
        if close_utc <= cutoff
        else close_utc.date() + timedelta(days=1)
    )


def parse_closing_time(value: Any) -> time:
    match = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", str(value).upper())
    if match:
        hour = int(match.group(1)) % 12
        if match.group(3) == "PM":
            hour += 12
        return time(hour, int(match.group(2)))
    match = re.search(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        raise CanonicalValueError(f"Invalid exchange closingHour: {value}.")
    return time(int(match.group(1)), int(match.group(2)))


def matches_keys(row: dict[str, Any], source: dict[str, Any]) -> bool:
    normalized = {normalize_name(key): value for key, value in row.items()}
    key_fields = source.get("key_fields") or {}
    for key, expected in (source.get("key_values") or {}).items():
        field = key_fields.get(key) or key
        actual = normalized.get(normalize_name(field))
        if key_text(actual) != key_text(expected):
            return False
    return True


def raw_json_value(value: Any, measure: str) -> float | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, dict):
        for key, child in value.items():
            if normalize_name(key) == normalize_name(measure):
                parsed = finite_float(child)
                if parsed is not None:
                    return parsed
        for child in value.values():
            parsed = raw_json_value(child, measure)
            if parsed is not None:
                return parsed
    if isinstance(value, list):
        for child in value:
            parsed = raw_json_value(child, measure)
            if parsed is not None:
                return parsed
    return None


def series_receipt(series: dict[date, float]) -> str:
    return digest(
        [
            [day.isoformat(), format(float(value), ".17g")]
            for day, value in sorted(series.items())
            if math.isfinite(float(value))
        ]
    )


def digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def required_date(value: Any, *, label: str) -> date:
    parsed = parse_date(value)
    if parsed is None:
        raise CanonicalValueError(
            f"Canonical source {label} must be an ISO date."
        )
    return parsed


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def key_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return str(value)
