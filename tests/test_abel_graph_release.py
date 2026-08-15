"""Graph-release configuration and CAP-backed discovery contracts."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from abel_edge.cli import main
from abel_edge.plugins.abel.client import AbelClient
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
            "release_id": "allnodes_causal_graph_20260721",
        },
        "expected_release_receipt_sha256": "a" * 64,
    }


def test_graph_release_hash_is_canonical_and_credentials_are_forbidden():
    left = GraphReleaseConfig.from_mapping(_v4_release())
    right_payload = _v4_release()
    right_payload["graph_ref"] = {
        "release_id": "allnodes_causal_graph_20260721",
        "graph_version": "CausalNodeV4",
        "graph_id": "abel-main",
    }
    right = GraphReleaseConfig.from_mapping(right_payload)

    assert left.sha256 == right.sha256
    assert left.graph_ref == _v4_release()["graph_ref"]

    unsafe = _v4_release()
    unsafe["api_key"] = "secret"
    with pytest.raises(GraphReleaseContractError, match="credential"):
        GraphReleaseConfig.from_mapping(unsafe)


@pytest.mark.parametrize("missing", ["release_id", "receipt"])
def test_v4_release_requires_frozen_release_identity(missing):
    payload = _v4_release()
    if missing == "release_id":
        payload["graph_ref"].pop("release_id")
    else:
        payload.pop("expected_release_receipt_sha256")

    with pytest.raises(GraphReleaseContractError, match=missing.replace("_", " ")):
        GraphReleaseConfig.from_mapping(payload)


def test_v3_release_keeps_legacy_graph_ref_without_release_receipt():
    release = GraphReleaseConfig.from_mapping(
        {
            "contract": "abel-edge.graph-release/v1",
            "provider": "abel",
            "graph_ref": {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV3",
            },
        }
    )

    assert release.graph_ref == {
        "graph_id": "abel-main",
        "graph_version": "CausalNodeV3",
    }


def test_discover_sends_caller_graph_release_ref():
    class StubResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": []}

    class StubSession:
        def __init__(self):
            self.calls = []

        def post(self, url, json=None, headers=None, timeout=20):
            self.calls.append({"url": url, "json": json})
            return StubResponse()

    graph_ref = {
        "graph_id": "abel-main",
        "graph_version": "CausalNodeV4",
        "release_id": "allnodes_causal_graph_20260721",
    }
    session = StubSession()

    AbelClient(session=session).discover_parents(
        node_id="catalog::demo",
        limit=5,
        api_key="abel_test",
        graph_ref=graph_ref,
    )

    request = session.calls[0]["json"]
    assert request["context"]["graph_ref"] == graph_ref
    assert request["params"]["node_id"] == "catalog::demo"


def test_v4_discovery_preserves_arbitrary_node_identity(monkeypatch):
    from abel_edge.plugins.abel import discover as discover_module

    release = GraphReleaseConfig.from_mapping(_v4_release())

    class StubClient:
        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            assert node_id == "AAPL.price"
            assert graph_ref == release.graph_ref
            return [
                {
                    "node_id": "catalog::market.index.price.daily::open::deadbeef",
                    "family": "catalog_log_return_then_robust_asinh_deseason",
                    "source_rank": 7,
                    "node_spec_sha256": "b" * 64,
                }
            ]

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")
    payload = discover_module.discover_graph_payload(
        "AAPL.price",
        mode="parents",
        graph_release=release,
        client=StubClient(),
    )

    assert payload["contract"] == "abel-edge.graph-discovery/v2"
    assert payload["graph_release_sha256"] == release.sha256
    assert payload["parents"][0]["node_id"].startswith("catalog::")
    assert payload["parents"][0]["driver_ref"] == {
        "kind": "canonical_node",
        "node_id": "catalog::market.index.price.daily::open::deadbeef",
        "family": "catalog_log_return_then_robust_asinh_deseason",
        "node_spec_sha256": "b" * 64,
    }
    assert payload["parents"][0]["source_rank"] == 7


def test_graph_release_doctor_blocks_v4_without_cap_descriptor(monkeypatch, tmp_path):
    from abel_edge.plugins.abel import graph_release as release_module

    config_path = tmp_path / "v4.json"
    config_path.write_text(json.dumps(_v4_release()), encoding="utf-8")

    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            return [{"node_id": "JWWCX.price", "display_name": "Legacy ticker"}]

        def graph_provenance(self):
            return {"graph_version": "CausalNodeV4"}

    monkeypatch.setattr(release_module, "require_api_key", lambda **_: "test")
    monkeypatch.setattr(release_module, "AbelClient", lambda **_: StubClient())

    result = CliRunner().invoke(
        main,
        [
            "graph-release",
            "doctor",
            "--graph-release",
            str(config_path),
            "--ticker",
            "AAPL.price",
            "--json",
        ],
    )

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["contract"] == "abel-edge.graph-release-doctor/v1"
    assert payload["status"] == "blocked"
    assert payload["checks"]["release_identity"]["status"] == "blocked"
    assert payload["checks"]["canonical_descriptor"]["status"] == "blocked"
    assert "raw-only" in payload["summary"]
