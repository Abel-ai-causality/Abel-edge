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
        },
    }


def test_graph_release_hash_is_canonical_and_credentials_are_forbidden():
    left = GraphReleaseConfig.from_mapping(_v4_release())
    right_payload = _v4_release()
    right_payload["graph_ref"] = {
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


def test_v4_release_is_the_cap_graph_ref_not_a_legacy_s3_package():
    release = GraphReleaseConfig.from_mapping(_v4_release())

    assert release.graph_ref == {
        "graph_id": "abel-main",
        "graph_version": "CausalNodeV4",
    }
    assert release.expected_release_receipt_sha256 is None


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


def test_v4_discovery_expands_a_plain_ticker_to_public_price_target():
    class StubResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": []}

    class StubSession:
        def __init__(self):
            self.body = None

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.body = json
            return StubResponse()

    session = StubSession()
    AbelClient(session=session).discover_parents(
        node_id="AAPL",
        limit=5,
        api_key="abel_test",
        graph_ref=_v4_release()["graph_ref"],
    )

    assert session.body["params"]["node_id"] == "AAPL.price"


def test_v4_discovery_routes_market_nodes_through_adjusted_symbol_mode(monkeypatch):
    from abel_edge.plugins.abel import discover as discover_module

    release = GraphReleaseConfig.from_mapping(_v4_release())

    class StubClient:
        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            assert node_id == "AAPL.price"
            assert graph_ref == release.graph_ref
            return [
                {"node_id": "BRE.AX_close"},
                {"node_id": "ONEE.BK_volume"},
                {"node_id": "JWWCX.price"},
                {"node_id": "000001.SZ.volume"},
            ]

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")
    payload = discover_module.discover_graph_payload(
        "AAPL.price",
        mode="parents",
        graph_release=release,
        client=StubClient(),
    )

    assert [item["driver_ref"] for item in payload["parents"]] == [
        {
            "kind": "symbol",
            "graph_node_id": "BRE.AX_close",
            "symbol": "BRE.AX",
            "field": "close",
            "adjustment": "provider_symbol_mode",
            "timezone": "UTC",
        },
        {
            "kind": "symbol",
            "graph_node_id": "ONEE.BK_volume",
            "symbol": "ONEE.BK",
            "field": "volume",
            "adjustment": "provider_symbol_mode",
            "timezone": "UTC",
        },
        {
            "kind": "symbol",
            "graph_node_id": "JWWCX.price",
            "symbol": "JWWCX",
            "field": "close",
            "adjustment": "provider_symbol_mode",
            "timezone": "UTC",
        },
        {
            "kind": "symbol",
            "graph_node_id": "000001.SZ.volume",
            "symbol": "000001.SZ",
            "field": "volume",
            "adjustment": "provider_symbol_mode",
            "timezone": "UTC",
        },
    ]
    assert [item["source_rank"] for item in payload["parents"]] == [1, 2, 3, 4]


def test_v4_discovery_preserves_arbitrary_node_identity(monkeypatch):
    from abel_edge.plugins.abel import discover as discover_module

    release = GraphReleaseConfig.from_mapping(_v4_release())

    class StubClient:
        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            return [
                {
                    "node_id": "health.openfda.drug.events:event_count#96bc3e82",
                    "source_rank": 7,
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
    assert payload["parents"][0]["node_id"].startswith("health.openfda")
    assert payload["parents"][0]["family"] == "health.openfda.drug.events"
    assert payload["parents"][0]["driver_ref"] == {
        "kind": "canonical_node",
        "node_id": "health.openfda.drug.events:event_count#96bc3e82",
        "retrieval_mode": "node_id",
        "adjustment": "none",
        "timezone": "UTC",
        "series_semantics": "point_in_time_scalar",
    }
    assert payload["parents"][0]["source_rank"] == 7
    rendered = discover_module.render_discovery_payload(payload, mode="parents")
    assert "node_id: health.openfda.drug.events:event_count#96bc3e82" in rendered
    assert "kind: canonical_node" in rendered


def test_graph_release_doctor_blocks_non_scalar_raw_node_records(monkeypatch, tmp_path):
    from abel_edge.plugins.abel import graph_release as release_module

    config_path = tmp_path / "v4.json"
    config_path.write_text(json.dumps(_v4_release()), encoding="utf-8")

    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            return [
                {"node_id": "JWWCX.price"},
                {"node_id": "health.openfda.drug.events:event_count#96bc3e82"},
            ]

        def graph_provenance(self):
            return {"graph_version": "CausalNodeV4"}

        def fetch_bars(self, *, symbols, start, end, timeframe, limit, fields, api_key):
            assert symbols == ["JWWCX"]
            assert fields == ["close"]
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "JWWCX",
                    "close": 10.0,
                }
            ]

        def fetch_node_series_page(self, *, node_id, start, end, limit, cursor_id, api_key):
            return {
                "mode": "node_records",
                "node": {
                    "node_id": node_id,
                    "source_table": "his_openfda_drug_event_daily",
                    "feature": "event_count",
                },
                "data": [
                    {"id": 1, "date": "2026-05-01", "event_count": 1},
                    {"id": 2, "date": "2026-05-01", "event_count": 2},
                ],
                "page": {"limit": 100, "max_id": 2, "has_more": False},
            }

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
    assert payload["checks"]["release_identity"]["status"] == "pass"
    assert payload["checks"]["market_symbol_routes"]["status"] == "pass"
    assert payload["checks"]["node_id_scalar_series"]["status"] == "blocked"
    assert "not scalar-series mode" in payload["checks"]["node_id_scalar_series"]["reasons"][0]
    assert "scalar-series" in payload["summary"]


def test_graph_release_doctor_accepts_exact_scalar_node_series(monkeypatch, tmp_path):
    from abel_edge.plugins.abel import graph_release as release_module

    config_path = tmp_path / "v4.json"
    config_path.write_text(json.dumps(_v4_release()), encoding="utf-8")

    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            return [
                {"node_id": "JWWCX.price"},
                {"node_id": "000001.SZ.volume"},
                {"node_id": "health.openfda.drug.events:event_count#96bc3e82"},
            ]

        def graph_provenance(self):
            return {"graph_version": "CausalNodeV4"}

        def fetch_bars(self, *, symbols, start, end, timeframe, limit, fields, api_key):
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": symbols[0],
                    fields[0]: 10.0,
                }
            ]

        def fetch_node_series_page(self, *, node_id, start, end, limit, cursor_id, api_key):
            return {
                "mode": "node_series",
                "node": {"node_id": node_id, "feature": "event_count"},
                "data": [
                    {"timestamp": "2026-05-01T00:00:00Z", "value": 21.0},
                    {"timestamp": "2026-05-02T00:00:00Z", "value": 25.0},
                ],
                "page": {"limit": 100, "max_id": 2, "has_more": False},
            }

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
            "ABG.price",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ready"
    assert payload["checks"]["market_symbol_routes"]["status"] == "pass"
    assert payload["checks"]["node_id_scalar_series"]["status"] == "pass"
