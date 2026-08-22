"""Regressions for the latest graph-release review findings."""

from __future__ import annotations

import pytest

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
