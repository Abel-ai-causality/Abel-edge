"""Live, fail-closed checks for one CAP-backed Abel graph release."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from abel_edge.plugins.abel.client import split_public_node_id
from abel_edge.plugins.abel.graph_driver import classify_v4_driver
from abel_edge.plugins.abel.graph_provenance import graph_provenance_reasons
from abel_edge.plugins.abel.graph_release import GRAPH_RELEASE_DOCTOR_CONTRACT

PROBE_START = "2026-05-01"
PROBE_END = "2026-05-28"
PROBE_LIMIT = 100


def assess_graph_release(*, release, api_key: str, client, ticker: str) -> dict[str, Any]:
    methods = client.cap_methods(api_key=api_key)
    parents = client.discover_parents(
        node_id=ticker,
        limit=20,
        api_key=api_key,
        graph_ref=release.graph_ref,
    )
    parents_provenance = client.graph_provenance()
    blanket_items = client.markov_blanket(
        node_id=ticker,
        limit=20,
        api_key=api_key,
        graph_ref=release.graph_ref,
    )
    blanket_provenance = client.graph_provenance()
    observed_provenance = {
        "parents": parents_provenance,
        "markov_blanket": blanket_provenance,
    }
    identity_reasons = [
        f"{route}: {reason}"
        for route, provenance in observed_provenance.items()
        for reason in graph_provenance_reasons(release, provenance)
    ]
    parent_routes = _route_parents(parents, canonical=release.is_canonical)
    blanket_routes = _route_parents(blanket_items, canonical=release.is_canonical)
    routed = _unique_routes([*parent_routes, *blanket_routes])
    unrouted_parent_count = len(parents) - len(parent_routes)
    unrouted_blanket_count = len(blanket_items) - len(blanket_routes)
    discovery_reasons = []
    if not parents:
        discovery_reasons.append("CAP discovery returned no parents")
    if unrouted_parent_count:
        discovery_reasons.append(
            f"{unrouted_parent_count} discovered parent(s) lacked a routable node identity"
        )
    blanket_reasons = []
    if unrouted_blanket_count:
        blanket_reasons.append(
            f"{unrouted_blanket_count} Markov-blanket item(s) lacked a routable node identity"
        )
    market_reasons = _probe_market_routes(routed, client=client, api_key=api_key)
    node_reasons, node_details = _probe_node_routes(
        routed,
        client=client,
        api_key=api_key,
    )
    checks = {
        "config": {"status": "pass"},
        "cap_methods": {
            "status": "pass" if methods else "blocked",
            "method_count": len(methods),
        },
        "discovery": {
            "status": "blocked" if discovery_reasons else "pass",
            "reasons": discovery_reasons,
            "parent_count": len(parents),
            "unrouted_parent_count": unrouted_parent_count,
            "market_parent_count": sum(
                item["driver_ref"]["kind"] == "symbol" for item in parent_routes
            ),
            "node_id_parent_count": sum(
                item["driver_ref"]["kind"] == "canonical_node" for item in parent_routes
            ),
        },
        "markov_blanket": {
            "status": "blocked" if blanket_reasons else "pass",
            "reasons": blanket_reasons,
            "item_count": len(blanket_items),
            "unrouted_item_count": unrouted_blanket_count,
            "market_item_count": sum(
                item["driver_ref"]["kind"] == "symbol" for item in blanket_routes
            ),
            "node_id_item_count": sum(
                item["driver_ref"]["kind"] == "canonical_node"
                for item in blanket_routes
            ),
        },
        "release_identity": _check(identity_reasons, observed=observed_provenance),
        "market_symbol_routes": _check(market_reasons),
        "node_id_scalar_series": _check(node_reasons, details=node_details),
    }
    blocked = [name for name, check in checks.items() if check["status"] != "pass"]
    status = "blocked" if blocked else "ready"
    summary = (
        "CAP graph release is ready for Edge typed-driver consumption."
        if status == "ready"
        else "CAP routing is reachable, but identity or scalar-series semantics are incomplete."
    )
    return {
        "contract": GRAPH_RELEASE_DOCTOR_CONTRACT,
        "status": status,
        "summary": summary,
        "graph_release": release.payload,
        "graph_release_sha256": release.sha256,
        "ticker": ticker,
        "probe_window": {"start": PROBE_START, "end": PROBE_END},
        "checks": checks,
        "blocked_checks": blocked,
    }


def _route_parents(
    parents: list[dict[str, Any]],
    *,
    canonical: bool,
) -> list[dict[str, Any]]:
    routed = []
    for index, item in enumerate(parents, start=1):
        node_id = _node_id(item)
        if not node_id:
            continue
        source_rank = int(item.get("source_rank", index))
        if canonical:
            routed.append(
                classify_v4_driver(
                    item,
                    node_id=node_id,
                    source_rank=source_rank,
                )
            )
            continue
        try:
            symbol, graph_field = split_public_node_id(node_id)
        except ValueError:
            continue
        field = "close" if graph_field == "price" else graph_field
        routed.append(
            {
                "node_id": node_id,
                "source_rank": source_rank,
                "driver_ref": {
                    "kind": "symbol",
                    "symbol": symbol,
                    "field": field,
                },
            }
        )
    return routed


def _unique_routes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = []
    seen = set()
    for item in items:
        ref = item["driver_ref"]
        identity = (
            ref["kind"],
            ref.get("symbol") or ref.get("node_id"),
            ref.get("field"),
        )
        if identity not in seen:
            seen.add(identity)
            unique.append(item)
    return unique


def _probe_market_routes(routed, *, client, api_key: str) -> list[str]:
    reasons = []
    seen = set()
    for item in routed:
        ref = item["driver_ref"]
        if ref["kind"] != "symbol":
            continue
        identity = (ref["symbol"], ref["field"])
        if identity in seen:
            continue
        seen.add(identity)
        try:
            rows = client.fetch_bars(
                symbols=[ref["symbol"]],
                start=PROBE_START,
                end=PROBE_END,
                timeframe="1d",
                limit=PROBE_LIMIT,
                fields=[ref["field"]],
                api_key=api_key,
            )
        except Exception as exc:
            reasons.append(f"{item['node_id']}: symbol route failed: {exc}")
            continue
        if not _has_finite_market_row(rows, ref["field"], ref["symbol"]):
            reasons.append(
                f"{item['node_id']}: symbol route returned no finite "
                f"{ref['field']} values for {ref['symbol']}"
            )
    return reasons


def _probe_node_routes(routed, *, client, api_key: str) -> tuple[list[str], list[dict[str, Any]]]:
    reasons = []
    details = []
    for item in routed:
        ref = item["driver_ref"]
        if ref["kind"] != "canonical_node":
            continue
        node_id = ref["node_id"]
        try:
            rows = client.fetch_node_series(
                node_id=node_id,
                start=PROBE_START,
                end=PROBE_END,
                limit=None,
                api_key=api_key,
            )
        except Exception as exc:
            reasons.append(f"{node_id}: node_id route failed: {exc}")
            continue
        if not isinstance(rows, list):
            reasons.append(f"{node_id}: scalar-series response is missing data")
            continue
        if any(
            not isinstance(row, dict)
            or str(row.get("node_id") or "").strip() != node_id
            for row in rows
        ):
            reasons.append(f"{node_id}: response did not preserve the exact node identity")
            continue
        feature = "value"
        times = [_event_time(row) for row in rows]
        usable = [time for time in times if time]
        duplicate_count = len(usable) - len(set(usable))
        finite_count = sum(_finite(row.get("value")) for row in rows if isinstance(row, dict))
        details.append(
            {
                "node_id": node_id,
                "feature": feature,
                "row_count": len(rows),
                "finite_value_count": finite_count,
                "duplicate_event_time_count": duplicate_count,
            }
        )
        if not rows or finite_count != len(rows) or len(usable) != len(rows):
            reasons.append(
                f"{node_id}: scalar series requires a finite value and UTC timestamp per row"
            )
        if duplicate_count:
            reasons.append(f"{node_id}: duplicate UTC timestamp in scalar series")
    return reasons, details


def _check(reasons: list[str], **details) -> dict[str, Any]:
    return {"status": "blocked" if reasons else "pass", "reasons": reasons, **details}


def _node_id(item: dict[str, Any]) -> str:
    for key in ("node_id", "id", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_finite_market_row(rows: Any, field: str, symbol: str) -> bool:
    expected_symbol = str(symbol or "").strip().upper()
    return isinstance(rows, list) and any(
        isinstance(row, dict)
        and str(row.get("symbol") or "").strip().upper() == expected_symbol
        and (event_time := _event_time(row))
        and PROBE_START <= event_time[:10] <= PROBE_END
        and _finite(row.get(field))
        for row in rows
    )


def _event_time(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    text = str(row.get("timestamp") or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False
