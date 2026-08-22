"""Regressions for the second PR review of graph-release support."""

from __future__ import annotations

import hashlib

import pandas as pd

from abel_edge.engine.feed_loader import load_feed_frame
from abel_edge.plugins.abel.graph_release import GraphReleaseConfig
from abel_edge.plugins.abel.graph_release import default_v3_graph_release
from abel_edge.plugins.abel.graph_provenance import graph_provenance_reasons
from abel_edge.plugins.abel.graph_release_doctor import (
    _probe_node_routes,
    assess_graph_release,
)
from abel_edge.plugins.abel.node_records_client import fetch_all_node_series


NODE_ID = "health.openfda.drug.events:event_count#96bc3e82"


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


def test_doctor_verifies_every_configured_graph_selector():
    release = _v4_release()

    mismatched = graph_provenance_reasons(
        release,
        {
            "graph_id": "another-graph",
            "graph_version": "CausalNodeV4",
            "edge_set": "precision",
        },
    )
    missing = graph_provenance_reasons(
        release,
        {
            "graph_id": "abel-main",
            "graph_version": "CausalNodeV4",
        },
    )

    assert any("graph_id" in reason and "another-graph" in reason for reason in mismatched)
    assert any("edge_set" in reason and "precision" in reason for reason in mismatched)
    assert any("edge_set" in reason and "<missing>" in reason for reason in missing)


def test_point_in_time_date_only_end_includes_the_whole_utc_day(tmp_path):
    path = tmp_path / "canonical.csv"
    path.write_text(
        "observed_at,released_at,reading\n"
        "2024-01-01T05:00:00Z,2024-01-03T05:00:00Z,1\n"
        "2024-01-02T05:00:00Z,2024-01-04T00:00:00Z,2\n",
        encoding="utf-8",
    )
    spec = {
        "contract": "abel-edge.point-in-time-series/v1",
        "series_id": "canonical.review.date-end",
        "source": {
            "adapter": "csv",
            "request": {"path": str(path)},
        },
        "schema": {
            "event_time_field": "observed_at",
            "available_at_field": "released_at",
            "value_field": "reading",
        },
        "materialization": {
            "frequency": "irregular",
            "timezone": "UTC",
            "missing_policy": "none",
            "alignment_policy": "native_only",
        },
        "transforms": [],
        "availability": {"mode": "explicit"},
        "provenance": {
            "source_receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }

    frame = load_feed_frame(
        {
            "name": "canonical",
            "kind": "point_in_time_series",
            "adapter": "csv",
            "profile": "daily",
            "series_spec": spec,
        },
        end="2024-01-03",
    )

    assert list(frame["timestamp"]) == [pd.Timestamp("2024-01-03T05:00:00Z")]
    assert list(frame["value"]) == [1]


def test_doctor_uses_paginated_node_series_path_and_rejects_stalled_cursor():
    class StubClient:
        def __init__(self):
            self.calls = []

        def fetch_node_series_page(
            self, *, node_id, start, end, limit, cursor_date, api_key
        ):
            self.calls.append(cursor_date)
            day = "2026-05-01" if cursor_date is None else "2026-05-02"
            return {
                "mode": "node_series",
                "node": {"node_id": node_id, "feature": "event_count"},
                "data": [
                    {
                        "timestamp": f"{day}T05:00:00Z",
                        "value": float(len(self.calls)),
                    }
                ],
                "page": {
                    "max_date": "2026-05-01",
                    "has_more": True,
                },
            }

        def fetch_node_series(self, *, node_id, start, end, limit, api_key):
            return fetch_all_node_series(
                fetch_page=self.fetch_node_series_page,
                node_id=node_id,
                start=start,
                end=end,
                limit=limit,
                api_key=api_key,
            )

    client = StubClient()
    routed = [
        {
            "node_id": NODE_ID,
            "driver_ref": {"kind": "canonical_node", "node_id": NODE_ID},
        }
    ]

    reasons, details = _probe_node_routes(routed, client=client, api_key="test")

    assert client.calls == [None, "2026-05-01"]
    assert details == []
    assert any("date cursor did not advance" in reason for reason in reasons)


def test_doctor_probes_v3_parent_symbol_routes():
    class StubClient:
        def __init__(self):
            self.bar_calls = []

        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price", "source_rank": 1}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return {"graph_id": "abel-main", "graph_version": "CausalNodeV3"}

        def fetch_bars(self, **kwargs):
            self.bar_calls.append(kwargs)
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "MSFT",
                    "close": 10.0,
                }
            ]

    client = StubClient()

    result = assess_graph_release(
        release=default_v3_graph_release(),
        api_key="test",
        client=client,
        ticker="AAPL.price",
    )

    assert result["status"] == "ready"
    assert result["checks"]["discovery"]["market_parent_count"] == 1
    assert len(client.bar_calls) == 1
    assert client.bar_calls[0]["symbols"] == ["MSFT"]
    assert client.bar_calls[0]["fields"] == ["close"]


def test_doctor_blocks_discovery_items_without_routable_node_identity():
    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}]

        def discover_parents(self, **_kwargs):
            return [{"unexpected": "missing-node-id"}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            }

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    assert result["checks"]["discovery"]["status"] == "blocked"
    assert result["checks"]["discovery"]["unrouted_parent_count"] == 1


def test_doctor_probes_markov_blanket_routes_before_reporting_ready():
    blanket_node = "health.openfda.drug.events:event_count#96bc3e82"

    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}, {"verb": "graph.markov_blanket"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            return [{"node_id": blanket_node, "roles": ["spouse"]}]

        def graph_provenance(self):
            return {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            }

        def fetch_bars(self, **_kwargs):
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "MSFT",
                    "close": 10.0,
                }
            ]

        def fetch_node_series(self, **_kwargs):
            raise ValueError("blanket node route unavailable")

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    assert result["checks"]["markov_blanket"]["status"] == "pass"
    assert result["checks"]["markov_blanket"]["node_id_item_count"] == 1
    assert "blanket node route unavailable" in result["checks"][
        "node_id_scalar_series"
    ]["reasons"][0]


def test_doctor_verifies_each_discovery_call_provenance_independently():
    class StubClient:
        def __init__(self):
            self.provenance = {}

        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}, {"verb": "graph.markov_blanket"}]

        def discover_parents(self, **_kwargs):
            self.provenance = {
                "graph_id": "wrong-graph",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            }
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            self.provenance = {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            }
            return []

        def graph_provenance(self):
            return dict(self.provenance)

        def fetch_bars(self, **_kwargs):
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "MSFT",
                    "close": 10.0,
                }
            ]

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    identity = result["checks"]["release_identity"]
    assert identity["status"] == "blocked"
    assert any("parents:" in reason and "wrong-graph" in reason for reason in identity["reasons"])
    assert identity["observed"]["parents"]["graph_id"] == "wrong-graph"
    assert identity["observed"]["markov_blanket"]["graph_id"] == "abel-main"


def test_doctor_rejects_market_rows_for_a_different_symbol():
    class StubClient:
        def cap_methods(self, *, api_key):
            return [{"verb": "traverse.parents"}, {"verb": "graph.markov_blanket"}]

        def discover_parents(self, **_kwargs):
            return [{"node_id": "MSFT.price"}]

        def markov_blanket(self, **_kwargs):
            return []

        def graph_provenance(self):
            return {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV4",
                "edge_set": "recall",
            }

        def fetch_bars(self, **_kwargs):
            return [
                {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "symbol": "AAPL",
                    "close": 10.0,
                }
            ]

    result = assess_graph_release(
        release=_v4_release(),
        api_key="test",
        client=StubClient(),
        ticker="AAPL.price",
    )

    assert result["status"] == "blocked"
    market_check = result["checks"]["market_symbol_routes"]
    assert market_check["status"] == "blocked"
    assert any("MSFT" in reason for reason in market_check["reasons"])
