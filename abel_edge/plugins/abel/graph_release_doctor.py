"""Live, fail-closed checks for one CAP-backed Abel graph release."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from abel_edge.plugins.abel.graph_driver import classify_v4_driver
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
    provenance = client.graph_provenance()
    identity_reasons = _identity_reasons(release, provenance)
    routed = _route_parents(parents) if release.is_canonical else []
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
            "status": "pass" if parents else "blocked",
            "parent_count": len(parents),
            "market_parent_count": sum(
                item["driver_ref"]["kind"] == "symbol" for item in routed
            ),
            "node_id_parent_count": sum(
                item["driver_ref"]["kind"] == "canonical_node" for item in routed
            ),
        },
        "release_identity": _check(identity_reasons, observed=provenance),
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


def _identity_reasons(release, provenance: dict[str, Any]) -> list[str]:
    reasons = []
    nested_ref = provenance.get("graph_ref")
    nested_ref = nested_ref if isinstance(nested_ref, dict) else {}
    for key, expected in release.graph_ref.items():
        observed = provenance.get(key, nested_ref.get(key))
        observed_text = str(observed or "")
        if observed_text != expected:
            reasons.append(
                f"expected {key}={expected}, observed={observed_text or '<missing>'}"
            )
    expected_receipt = release.expected_release_receipt_sha256
    observed_receipt = str(
        provenance.get("release_receipt_sha256")
        or provenance.get("release_sha256")
        or ""
    )
    if expected_receipt and observed_receipt != expected_receipt:
        reasons.append("configured release receipt was not reproduced by CAP")
    return reasons


def _route_parents(parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routed = []
    for index, item in enumerate(parents, start=1):
        node_id = _node_id(item)
        if node_id:
            routed.append(
                classify_v4_driver(
                    item,
                    node_id=node_id,
                    source_rank=int(item.get("source_rank", index)),
                )
            )
    return routed


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
        if not _has_finite_market_row(rows, ref["field"]):
            reasons.append(f"{item['node_id']}: symbol route returned no finite {ref['field']} values")
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


def _has_finite_market_row(rows: Any, field: str) -> bool:
    return isinstance(rows, list) and any(
        isinstance(row, dict) and row.get("timestamp") and _finite(row.get(field))
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
