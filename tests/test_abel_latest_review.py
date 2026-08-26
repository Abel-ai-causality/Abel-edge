"""Regressions for the latest graph-release review findings."""

from __future__ import annotations

import pytest

from abel_edge.engine.feed_contract import FeedDateGuardError
from abel_edge.plugins.abel import discover as discover_module
from abel_edge.plugins.abel import node_records_client
from abel_edge.plugins.abel.graph_release import (
    GraphReleaseConfig,
    GraphReleaseContractError,
)
from abel_edge.plugins.abel.graph_release_doctor import assess_graph_release


def _v4_release() -> GraphReleaseConfig:
    return GraphReleaseConfig.from_mapping(
        {
            "contract": "abel-edge.graph-release/v1",
            "provider": "abel",
            "graph_ref": {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            },
        }
    )


def _provenance(graph_id: str = "abel-main") -> dict[str, str]:
    return {
        "graph_id": graph_id,
        "graph_version": "CausalNodeV4",
        "edge_set": "recall",
    }


def test_discover_accepts_cap_v4_graph_version_only_provenance(monkeypatch):
    release = _v4_release()

    class StubClient:
        def __init__(self):
            self.requested_graph_ref = None

        def discover_parents(self, *, node_id, limit, api_key, graph_ref):
            self.requested_graph_ref = graph_ref
            return [{"node_id": "MSFT.price"}]

        def graph_provenance(self):
            return {
                "algorithm": "postgres.causal_edge_v4",
                "cap_spec_version": "0.2.2",
                "graph_version": "CausalNodeV4",
                "server_name": "abel-graph-computer",
            }

    client = StubClient()
    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    payload = discover_module.discover_graph_payload(
        "AAPL.price",
        mode="parents",
        graph_release=release,
        client=client,
    )

    assert client.requested_graph_ref == release.graph_ref
    assert [item["node_id"] for item in payload["parents"]] == ["MSFT.price"]


@pytest.mark.parametrize("wrong_route", ["parents", "markov_blanket"])
def test_discover_validates_each_cap_call_provenance_immediately(
    monkeypatch, wrong_route
):
    class StubClient:
        def __init__(self):
            self.provenance = {}

        def discover_parents(self, **_kwargs):
            graph_id = "wrong-graph" if wrong_route == "parents" else "abel-main"
            self.provenance = _provenance(graph_id)
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            graph_id = "wrong-graph" if wrong_route == "markov_blanket" else "abel-main"
            self.provenance = _provenance(graph_id)
            return []

        def graph_provenance(self):
            return dict(self.provenance)

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    with pytest.raises(GraphReleaseContractError, match=wrong_route):
        discover_module.discover_graph_payload(
            "AAPL.price",
            mode="all",
            graph_release=_v4_release(),
            client=StubClient(),
        )


def test_discover_rejects_release_receipt_mismatch(monkeypatch):
    release_payload = _v4_release().payload
    release_payload["expected_release_receipt_sha256"] = "a" * 64
    release = GraphReleaseConfig.from_mapping(release_payload)

    class StubClient:
        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def graph_provenance(self):
            return {**_provenance(), "release_receipt_sha256": "b" * 64}

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    with pytest.raises(GraphReleaseContractError, match="receipt"):
        discover_module.discover_graph_payload(
            "AAPL.price",
            mode="parents",
            graph_release=release,
            client=StubClient(),
        )


def test_discover_requires_explicit_release_id_to_be_reproduced(monkeypatch):
    release_payload = _v4_release().payload
    release_payload["graph_ref"]["release_id"] = "v4-release-20260824"
    release = GraphReleaseConfig.from_mapping(release_payload)

    class StubClient:
        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def graph_provenance(self):
            return {"graph_version": "CausalNodeV4"}

    monkeypatch.setattr(discover_module, "require_api_key", lambda **_: "test")

    with pytest.raises(GraphReleaseContractError, match="release_id"):
        discover_module.discover_graph_payload(
            "AAPL.price",
            mode="parents",
            graph_release=release,
            client=StubClient(),
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        "not-a-timestamp",
        "2026-05-01T00:00:00",
        "2026-04-30T23:59:59Z",
        "2026-05-29T00:00:00Z",
    ],
)
def test_doctor_rejects_market_rows_without_utc_time_in_probe_window(timestamp):
    class StubClient:
        def cap_methods(self, **_kwargs):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return _provenance()

        def fetch_bars(self, **_kwargs):
            return [{"timestamp": timestamp, "symbol": "MSFT", "close": 10.0}]

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    assert result["checks"]["market_symbol_routes"]["status"] == "blocked"


def test_doctor_rejects_probe_after_cutoff_before_cap_call(monkeypatch):
    monkeypatch.setenv("ABEL_EDGE_MAX_DATA_DATE", "2025-06-30")
    monkeypatch.setenv("ABEL_EDGE_DATE_GUARD_MODE", "fail-closed")
    calls = []

    class StubClient:
        def cap_methods(self, **_kwargs):
            calls.append("cap_methods")
            return []

        def discover_parents(self, **_kwargs):
            calls.append("discover_parents")
            return []

        def markov_blanket(self, **_kwargs):
            calls.append("markov_blanket")
            return []

        def graph_provenance(self):
            return _provenance()

    with pytest.raises(FeedDateGuardError, match="date_guard_violation"):
        assess_graph_release(
            release=_v4_release(),
            api_key="test",
            client=StubClient(),
            ticker="AAPL.price",
        )

    assert calls == []


def test_doctor_rejects_market_response_after_cutoff(monkeypatch):
    monkeypatch.setenv("ABEL_EDGE_MAX_DATA_DATE", "2026-05-28")
    monkeypatch.setenv("ABEL_EDGE_DATE_GUARD_MODE", "fail-closed")

    class StubClient:
        def cap_methods(self, **_kwargs):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return _provenance()

        def fetch_bars(self, **_kwargs):
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "MSFT",
                    "close": 10.0,
                },
                {
                    "timestamp": "2026-05-29T00:00:00Z",
                    "symbol": "MSFT",
                    "close": 11.0,
                },
            ]

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    assert result["checks"]["market_symbol_routes"]["status"] == "blocked"
    assert "ABEL_EDGE_MAX_DATA_DATE" in result["checks"]["market_symbol_routes"][
        "reasons"
    ][0]


def test_doctor_rejects_canonical_availability_after_cutoff(monkeypatch):
    monkeypatch.setenv("ABEL_EDGE_MAX_DATA_DATE", "2026-05-28")
    monkeypatch.setenv("ABEL_EDGE_DATE_GUARD_MODE", "fail-closed")
    node_id = "health.openfda.drug.events:event_count#96bc3e82"

    class StubClient:
        def cap_methods(self, **_kwargs):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": node_id}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return _provenance()

        def fetch_node_series(self, **_kwargs):
            return [
                {
                    "date": "2026-05-28",
                    "node_id": node_id,
                    "timestamp": "2026-05-30T00:00:00Z",
                    "value": 1.0,
                }
            ]

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    assert result["checks"]["node_id_scalar_series"]["status"] == "blocked"
    assert "ABEL_EDGE_MAX_DATA_DATE" in result["checks"]["node_id_scalar_series"][
        "reasons"
    ][0]


def test_doctor_cli_forwards_explicit_probe_window(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from abel_edge.cli import main
    from abel_edge.plugins.abel import graph_release as release_module
    from abel_edge.plugins.abel import graph_release_doctor as doctor_module

    config_path = tmp_path / "graph-release.json"
    config_path.write_text("{}", encoding="utf-8")
    observed = {}

    def fake_assess(**kwargs):
        observed.update(kwargs)
        return {"status": "ready", "summary": "ready", "blocked_checks": []}

    monkeypatch.setattr(release_module, "resolve_graph_release", lambda _value: object())
    monkeypatch.setattr(release_module, "require_api_key", lambda **_kwargs: "test")
    monkeypatch.setattr(release_module, "AbelClient", lambda **_kwargs: object())
    monkeypatch.setattr(doctor_module, "assess_graph_release", fake_assess)
    result = CliRunner().invoke(
        main,
        [
            "graph-release",
            "doctor",
            "--graph-release",
            str(config_path),
            "--probe-start",
            "2025-06-01",
            "--probe-end",
            "2025-06-30",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert observed["probe_start"] == "2025-06-01"
    assert observed["probe_end"] == "2025-06-30"


def test_node_series_rejects_capacity_exhaustion_before_later_year(monkeypatch):
    monkeypatch.setattr(node_records_client, "MAX_NODE_SERIES_ROWS", 2, raising=False)
    calls = []

    def fetch_page(**kwargs):
        calls.append(kwargs)
        year = str(kwargs["start"])[:4]
        days = (30, 31) if year == "2025" else (1,)
        return {
            "mode": "node_series",
            "node": {"node_id": "catalog:test#1"},
            "data": [
                {
                    "timestamp": f"{year}-{'12' if year == '2025' else '01'}-{day:02d}T00:00:00Z",
                    "value": float(day),
                }
                for day in days
            ],
            "page": {"has_more": False},
        }

    with pytest.raises(ValueError, match="safety cap"):
        node_records_client.fetch_all_node_series(
            fetch_page=fetch_page,
            node_id="catalog:test#1",
            start="2025-12-30",
            end="2026-01-02",
            limit=None,
            api_key="abel_test",
        )

    assert len(calls) == 1
