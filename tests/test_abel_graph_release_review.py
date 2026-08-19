"""Review regressions for graph-release selection and typed blanket nodes."""

from __future__ import annotations

import pytest

from abel_edge.plugins.abel import discover as discover_module
from abel_edge.plugins.abel.graph_release import (
    GraphReleaseConfig,
    GraphReleaseContractError,
)


def _v4_release() -> dict:
    return {
        "contract": "abel-edge.graph-release/v1",
        "provider": "abel",
        "graph_ref": {
            "graph_id": "abel-main",
            "graph_version": "CausalNodeV4",
        },
    }


def test_graph_release_rejects_unknown_graph_versions():
    unsupported = _v4_release()
    unsupported["graph_ref"]["graph_version"] = "CausalNodeV5"

    with pytest.raises(GraphReleaseContractError, match="supported graph_version"):
        GraphReleaseConfig.from_mapping(unsupported)


def test_v4_markov_blanket_preserves_typed_canonical_nodes(monkeypatch):
    release = GraphReleaseConfig.from_mapping(_v4_release())
    canonical_node = "health.openfda.drug.events:event_count#96bc3e82"
    canonical_child = "market.index.price.daily:close#38586e88"

    class StubClient:
        def discover_parents(self, **_kwargs):
            return []

        def markov_blanket(self, **_kwargs):
            return [
                {"node_id": canonical_node, "roles": ["spouse"]},
                {"node_id": canonical_child, "roles": ["child"]},
            ]

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")
    payload = discover_module.discover_graph_payload(
        "AAPL.price",
        mode="all",
        graph_release=release,
        client=StubClient(),
    )

    child = payload["children"][0]
    assert child["node_id"] == canonical_child
    assert child["driver_ref"]["kind"] == "canonical_node"
    assert child["roles"] == ["child"]
    item = payload["blanket_new"][0]
    assert item["node_id"] == canonical_node
    assert item["family"] == "health.openfda.drug.events"
    assert item["driver_ref"]["kind"] == "canonical_node"
    assert item["roles"] == ["spouse"]
    rendered = discover_module.render_discovery_payload(payload, mode="all")
    assert canonical_node in rendered
    assert canonical_child in rendered
    assert "kind: canonical_node" in rendered
    assert "roles: [spouse]" in rendered
