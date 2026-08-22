"""Shared fail-closed graph-release provenance checks."""

from __future__ import annotations

from typing import Any

from abel_edge.plugins.abel.graph_release import (
    GraphReleaseConfig,
    GraphReleaseContractError,
)


def graph_provenance_reasons(
    release: GraphReleaseConfig,
    provenance: dict[str, Any],
) -> list[str]:
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


def require_graph_provenance(
    client: Any,
    release: GraphReleaseConfig,
    *,
    route: str,
) -> dict[str, Any]:
    accessor = getattr(client, "graph_provenance", None)
    provenance = accessor() if callable(accessor) else None
    if not isinstance(provenance, dict):
        raise GraphReleaseContractError(
            f"CAP {route} provenance is unavailable; refusing discovery output."
        )
    reasons = graph_provenance_reasons(release, provenance)
    if reasons:
        raise GraphReleaseContractError(
            f"CAP {route} provenance does not match graph release: "
            + "; ".join(reasons)
        )
    return provenance
