"""Private JSON safety helpers for point-in-time series specs."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from abel_edge.engine.feed_contract import FeedContractError

_CREDENTIAL_KEY_PARTS = {
    "accesskey",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "secretkey",
    "token",
}


def finite_json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise FeedContractError(
            "series_spec must contain only finite JSON-serializable values."
        ) from exc


def find_credential_path(value: Any, *, prefix: str = "source.request") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(part in normalized for part in _CREDENTIAL_KEY_PARTS):
                return f"{prefix}.{key}"
            found = find_credential_path(child, prefix=f"{prefix}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = find_credential_path(child, prefix=f"{prefix}[{index}]")
            if found:
                return found
    return None
