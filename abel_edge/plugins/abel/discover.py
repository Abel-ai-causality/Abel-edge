"""Abel discovery helpers used by the CLI."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

from abel_edge.plugins.abel.client import AbelClient, split_public_node_id
from abel_edge.plugins.abel.credentials import MissingAbelApiKeyError, require_api_key
from abel_edge.plugins.abel.graph_release import (
    GRAPH_DISCOVERY_CONTRACT,
    GraphReleaseConfig,
    resolve_graph_release,
)


def discover_graph_nodes(
    node_id: str,
    *,
    mode: str = "parents",
    limit: int = 10,
    env_path: str = ".env",
    client: AbelClient | None = None,
    graph_release: GraphReleaseConfig | Mapping[str, Any] | str | Path | None = None,
) -> str:
    payload = discover_graph_payload(
        node_id,
        mode=mode,
        limit=limit,
        env_path=env_path,
        client=client,
        graph_release=graph_release,
    )
    return render_discovery_payload(payload, mode=mode)


def discover_graph_payload(
    node_id: str,
    *,
    mode: str = "all",
    limit: int = 10,
    env_path: str = ".env",
    client: AbelClient | None = None,
    graph_release: GraphReleaseConfig | Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    try:
        api_key = require_api_key(env_path=env_path)
    except MissingAbelApiKeyError as e:
        raise MissingAbelApiKeyError(
            f"{e} Optionally set ABEL_CAP_BASE_URL to target a non-default CAP endpoint."
        ) from e
    abel = client or AbelClient(env_path=env_path)
    release = resolve_graph_release(graph_release)
    limit = min(max(limit, 1), 20)

    if mode == "all":
        parents = _discover_mode_items(
            node_id=node_id,
            mode="parents",
            limit=limit,
            api_key=api_key,
            client=abel,
            release=release,
        )
        blanket_items = _discover_mode_items(
            node_id=node_id,
            mode="mb",
            limit=limit,
            api_key=api_key,
            client=abel,
            release=release,
        )
        return _build_discovery_payload(
            node_id,
            parents=parents,
            blanket_items=blanket_items,
            release=release,
        )

    items = _discover_mode_items(
        node_id=node_id,
        mode=mode,
        limit=limit,
        api_key=api_key,
        client=abel,
        release=release,
    )
    target_asset, target_node = _target_identity(node_id, release=release)
    if mode == "parents":
        return {
            "ticker": target_asset,
            "target_asset": target_asset,
            "target_node": target_node,
            "source": "abel_live",
            "mode": mode,
            "parents": items,
            "blanket_new": [],
            "children": [],
            "K_discovery": len(items),
            "created_at": _now(),
            "contract": GRAPH_DISCOVERY_CONTRACT,
            "graph_release": release.payload,
            "graph_release_sha256": release.sha256,
        }
    if mode == "mb":
        payload = _build_discovery_payload(
            node_id,
            parents=[],
            blanket_items=items,
            release=release,
        )
        payload["mode"] = mode
        payload["K_discovery"] = 0
        return payload
    raise ValueError(f"Unsupported mode '{mode}'.")


def render_discovery_payload(payload: dict[str, Any], *, mode: str = "all") -> str:
    if mode == "parents":
        return _render_parents(payload.get("parents", []))
    if mode == "mb":
        return _render_markov_blanket(
            payload.get("blanket_new", []),
            payload.get("children", []),
        )
    if mode == "all":
        return _render_combined(payload)
    raise ValueError(f"Unsupported mode '{mode}'.")


def _render_parents(items: list[dict[str, Any]]) -> str:
    lines = ["parents:"]
    for item in items[:20]:
        ticker = str(item.get("ticker", "")).strip()
        field = str(item.get("field", "")).strip()
        if not ticker or not field:
            continue
        lines.append(f"  - ticker: {ticker}")
        lines.append(f"    field: {field}")
    return "\n".join(lines)


def _render_markov_blanket(
    blanket_new: list[dict[str, Any]],
    children: list[dict[str, Any]],
) -> str:
    lines = ["markov_blanket:"]
    rendered_items = []
    for item in children:
        rendered_items.append(
            {
                "ticker": item.get("ticker", ""),
                "field": item.get("field", ""),
                "roles": ["child"],
            }
        )
    rendered_items.extend(blanket_new)
    for item in rendered_items[:20]:
        ticker = str(item.get("ticker", "")).strip()
        field = str(item.get("field", "")).strip()
        if not ticker or not field:
            continue
        roles = [str(role).strip() for role in item.get("roles", []) if str(role).strip()]
        lines.append(f"  - ticker: {ticker}")
        lines.append(f"    field: {field}")
        lines.append(f"    roles: [{', '.join(roles)}]")
    return "\n".join(lines)


def _render_combined(payload: dict[str, Any]) -> str:
    parts = [
        f"ticker: {payload.get('ticker', '')}",
        f"target_node: {payload.get('target_node', '')}",
        f"source: {payload.get('source', '')}",
        f"K_discovery: {payload.get('K_discovery', 0)}",
        _render_parents(payload.get("parents", [])),
        _render_markov_blanket(
            payload.get("blanket_new", []),
            payload.get("children", []),
        ),
    ]
    return "\n\n".join(part for part in parts if part)


def _discover_mode_items(
    *,
    node_id: str,
    mode: str,
    limit: int,
    api_key: str,
    client: AbelClient,
    release: GraphReleaseConfig,
) -> list[dict[str, Any]]:
    if mode == "parents":
        raw_items = _call_client_discovery(
            client.discover_parents,
            node_id=node_id,
            limit=limit,
            api_key=api_key,
            release=release,
        )
        return _normalize_items(raw_items, release=release)
    if mode == "mb":
        raw_items = _call_client_discovery(
            client.markov_blanket,
            node_id=node_id,
            limit=limit,
            api_key=api_key,
            release=release,
        )
        return _normalize_items(raw_items, release=release)
    raise ValueError(f"Unsupported mode '{mode}'.")


def _build_discovery_payload(
    node_id: str,
    *,
    parents: list[dict[str, Any]],
    blanket_items: list[dict[str, Any]],
    release: GraphReleaseConfig,
) -> dict[str, Any]:
    target_asset, target_node = _target_identity(node_id, release=release)
    parent_keys = {item["node_id"] for item in parents}
    children: list[dict[str, Any]] = []
    blanket_new: list[dict[str, Any]] = []
    seen_children: set[str] = set()
    seen_blanket: set[str] = set()

    for item in blanket_items:
        key = item["node_id"]
        roles = [str(role).strip() for role in item.get("roles", []) if str(role).strip()]
        if "child" in roles and key not in seen_children:
            children.append(
                {
                    "node_id": item["node_id"],
                    "ticker": item["ticker"],
                    "field": item["field"],
                }
            )
            seen_children.add(key)
            continue
        if key in parent_keys or key in seen_blanket:
            continue
        blanket_new.append(
            {
                "node_id": item["node_id"],
                "ticker": item["ticker"],
                "field": item["field"],
                "roles": roles or ["neighbor"],
            }
        )
        seen_blanket.add(key)

    return {
        "ticker": target_asset,
        "target_asset": target_asset,
        "target_node": target_node,
        "source": "abel_live",
        "parents": parents,
        "blanket_new": blanket_new,
        "children": children,
        "K_discovery": len(parents),
        "created_at": _now(),
        "contract": GRAPH_DISCOVERY_CONTRACT,
        "graph_release": release.payload,
        "graph_release_sha256": release.sha256,
    }


def _normalize_items(
    items: list[dict[str, Any]],
    *,
    release: GraphReleaseConfig,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items[:20], start=1):
        node_id = _pick_node_id(item)
        if not node_id:
            continue
        if release.is_canonical:
            node_spec = item.get("node_spec")
            family = str(
                item.get("family")
                or item.get("node_family")
                or (node_spec or {}).get("family")
                or ""
            ).strip()
            spec_sha = str(item.get("node_spec_sha256") or "").strip()
            if not spec_sha and isinstance(node_spec, Mapping):
                spec_sha = hashlib.sha256(
                    json.dumps(
                        node_spec,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            source_rank = item.get("source_rank", index)
            normalized.append(
                {
                    "node_id": node_id,
                    "family": family,
                    "source_rank": int(source_rank),
                    "node_spec_sha256": spec_sha,
                    "roles": _pick_roles(item),
                    "driver_ref": {
                        "kind": "canonical_node",
                        "node_id": node_id,
                        "family": family,
                        "node_spec_sha256": spec_sha,
                    },
                    **({"node_spec": dict(node_spec)} if isinstance(node_spec, Mapping) else {}),
                    **(
                        {"source_receipt_sha256": item["source_receipt_sha256"]}
                        if item.get("source_receipt_sha256")
                        else {}
                    ),
                }
            )
            continue
        ticker, field = split_public_node_id(node_id)
        normalized.append(
            {
                "node_id": f"{ticker}.{field}",
                "ticker": ticker,
                "field": field,
                "roles": _pick_roles(item),
                "source_rank": int(item.get("source_rank", index)),
                "driver_ref": {
                    "kind": "symbol",
                    "symbol": ticker,
                    "field": "close" if field == "price" else field,
                },
            }
        )
    return normalized


def _pick_node_id(item: dict[str, Any]) -> str:
    for key in ("node_id", "id", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pick_roles(item: dict[str, Any]) -> list[str]:
    for key in ("roles", "role", "relationship", "type"):
        value = item.get(key)
        if isinstance(value, list):
            return [str(role).strip() for role in value if str(role).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return ["neighbor"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_identity(
    node_id: str,
    *,
    release: GraphReleaseConfig,
) -> tuple[str, str]:
    if release.is_canonical:
        raw = str(node_id).strip()
        try:
            ticker, field = split_public_node_id(raw)
        except ValueError:
            return "", raw
        return ticker, f"{ticker}.{field}"
    ticker, field = split_public_node_id(node_id)
    return ticker, f"{ticker}.{field}"


def _call_client_discovery(
    method,
    *,
    node_id: str,
    limit: int,
    api_key: str,
    release: GraphReleaseConfig,
):
    """Keep legacy injected clients usable while the public client gains graph_ref."""

    kwargs = {"node_id": node_id, "limit": limit, "api_key": api_key}
    if "graph_ref" in inspect.signature(method).parameters:
        kwargs["graph_ref"] = release.graph_ref
    return method(**kwargs)
