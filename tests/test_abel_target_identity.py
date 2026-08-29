"""V3/V4 discovery target identity regressions."""

from __future__ import annotations

import pytest

from abel_edge.plugins.abel.graph_release import GraphReleaseConfig


def _v4_release() -> GraphReleaseConfig:
    return GraphReleaseConfig.from_mapping(
        {
            "contract": "abel-edge.graph-release/v1",
            "provider": "abel",
            "graph_ref": {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
            },
        }
    )


@pytest.mark.parametrize(
    ("requested", "expected_node", "expected_asset"),
    [
        ("BRK.B", "BRK.B.price", "BRK.B"),
        ("000858.SZ", "000858.SZ.price", "000858.SZ"),
    ],
)
def test_v4_discovery_uses_one_typed_market_target_identity(
    monkeypatch,
    requested,
    expected_node,
    expected_asset,
):
    from abel_edge.plugins.abel import discover as discover_module

    release = _v4_release()

    class StubClient:
        def __init__(self):
            self.requested_node = None

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            self.requested_node = node_id
            return []

        def graph_provenance(self):
            return release.graph_ref

    client = StubClient()
    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    payload = discover_module.discover_graph_payload(
        requested,
        mode="parents",
        graph_release=release,
        client=client,
    )

    assert client.requested_node == expected_node
    assert payload["ticker"] == expected_asset
    assert payload["target_asset"] == expected_asset
    assert payload["target_node"] == expected_node
    assert payload["target_ref"]["node_id"] == expected_node
    assert payload["target_ref"]["ticker"] == expected_asset
    assert payload["target_ref"]["driver_ref"]["graph_node_id"] == expected_node


def test_v4_discovery_uses_one_typed_canonical_target_identity(monkeypatch):
    from abel_edge.plugins.abel import discover as discover_module

    release = _v4_release()
    canonical_node = "health.openfda.drug.events:event_count#96bc3e82"

    class StubClient:
        def __init__(self):
            self.requested_node = None

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            self.requested_node = node_id
            return []

        def graph_provenance(self):
            return release.graph_ref

    client = StubClient()
    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    payload = discover_module.discover_graph_payload(
        canonical_node,
        mode="parents",
        graph_release=release,
        client=client,
    )

    assert client.requested_node == canonical_node
    assert payload["ticker"] == ""
    assert payload["target_asset"] == ""
    assert payload["target_node"] == canonical_node
    assert payload["target_ref"]["node_id"] == canonical_node
    assert payload["target_ref"]["driver_ref"]["kind"] == "canonical_node"


def test_v3_discovery_keeps_legacy_call_and_target_payload(monkeypatch):
    from abel_edge.plugins.abel import discover as discover_module

    class StubClient:
        def __init__(self):
            self.requested_node = None

        def discover_parents(self, *, node_id, limit, api_key):
            self.requested_node = node_id
            return []

        def graph_provenance(self):
            return {"graph_version": "CausalNodeV3"}

    client = StubClient()
    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    payload = discover_module.discover_graph_payload(
        "ETHUSD",
        mode="parents",
        client=client,
    )

    assert client.requested_node == "ETHUSD"
    assert payload["ticker"] == "ETHUSD"
    assert payload["target_asset"] == "ETHUSD"
    assert payload["target_node"] == "ETHUSD.price"
    assert "target_ref" not in payload
    assert payload["graph_release"]["graph_ref"]["graph_version"] == "CausalNodeV3"
