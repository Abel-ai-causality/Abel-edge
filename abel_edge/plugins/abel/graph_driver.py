"""Typed routing for drivers returned by the CAP CausalNodeV4 graph."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping


MARKET_PRICE_FAMILY = "market_price"
MARKET_VOLUME_FAMILY = "market_volume"


def normalize_graph_query_node_id(
    value: str,
    *,
    graph_version: str,
    legacy_normalizer: Callable[[str], str],
) -> str:
    """Expand a plain V4 ticker while preserving native canonical node IDs."""

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Ticker or node id cannot be empty.")
    if graph_version != "CausalNodeV4":
        return legacy_normalizer(raw)
    lowered = raw.lower()
    if ":" in raw or "#" in raw or lowered.endswith(("_close", "_volume")):
        return raw
    if lowered.endswith((".price", ".volume")):
        ticker, _, field = raw.rpartition(".")
        return f"{ticker.upper()}.{field.lower()}"
    return f"{raw.upper()}.price"


def resolve_graph_target(
    value: str,
    *,
    graph_version: str,
    legacy_normalizer: Callable[[str], str],
    legacy_splitter: Callable[[str], tuple[str, str]],
) -> tuple[str, dict[str, Any]]:
    """Resolve the query and payload identity from one graph-version rule."""

    if graph_version == "CausalNodeV4":
        query_node_id = normalize_graph_query_node_id(
            value,
            graph_version=graph_version,
            legacy_normalizer=legacy_normalizer,
        )
        target_ref = describe_v4_node(query_node_id)
        target_asset = str(target_ref.get("ticker") or "")
        return query_node_id, {
            "ticker": target_asset,
            "target_asset": target_asset,
            "target_node": target_ref["node_id"],
            "target_ref": target_ref,
        }
    ticker, field = legacy_splitter(value)
    return value, {
        "ticker": ticker,
        "target_asset": ticker,
        "target_node": f"{ticker}.{field}",
    }


def classify_v4_driver(
    item: Mapping[str, Any],
    *,
    node_id: str,
    source_rank: int,
) -> dict[str, Any]:
    """Preserve graph identity while choosing the safe CAP data route."""

    routed = describe_v4_node(node_id)
    routed["source_rank"] = source_rank
    return routed


def describe_v4_node(node_id: str) -> dict[str, Any]:
    """Describe one exact V4 graph node and its safe data route."""

    node_id = str(node_id or "").strip()
    if not node_id:
        raise ValueError("V4 graph node id cannot be empty.")

    market = parse_market_node_id(node_id)
    if market is not None:
        symbol, field = market
        driver_ref = {
            "kind": "symbol",
            "graph_node_id": node_id,
            "symbol": symbol,
            "field": field,
            "adjustment": "provider_symbol_mode",
            "timezone": "UTC",
        }
        return {
            "node_id": node_id,
            "ticker": symbol,
            "field": field,
            "family": MARKET_PRICE_FAMILY if field == "close" else MARKET_VOLUME_FAMILY,
            "driver_ref": driver_ref,
            "driver_ref_sha256": _digest(driver_ref),
        }

    driver_ref = {
        "kind": "canonical_node",
        "node_id": node_id,
        "retrieval_mode": "node_id",
        "adjustment": "none",
        "timezone": "UTC",
        "series_semantics": "point_in_time_scalar",
    }
    return {
        "node_id": node_id,
        "family": infer_raw_node_family(node_id),
        "driver_ref": driver_ref,
        "driver_ref_sha256": _digest(driver_ref),
    }


def parse_market_node_id(node_id: str) -> tuple[str, str] | None:
    """Return symbol/field for CAP V4 price and volume node naming forms."""

    raw = str(node_id or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    suffixes = (
        (".price", "close"),
        (".volume", "volume"),
        ("_close", "close"),
        ("_volume", "volume"),
    )
    for suffix, field in suffixes:
        if lowered.endswith(suffix):
            symbol = raw[: -len(suffix)].strip()
            if symbol:
                return symbol, field
    return None


def infer_raw_node_family(node_id: str) -> str:
    """Use the namespace before the measure separator as a stable family label."""

    namespace, separator, _measure = str(node_id or "").partition(":")
    return namespace if separator and namespace else "canonical_node"


def _digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
