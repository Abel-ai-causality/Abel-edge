"""Regressions for the second PR review of graph-release support."""

from __future__ import annotations

import hashlib

import pandas as pd

from abel_edge.engine.feed_loader import load_feed_frame
from abel_edge.plugins.abel.canonical_source_window import (
    resolve_materialization_window,
)
from abel_edge.plugins.abel.graph_release import GraphReleaseConfig
from abel_edge.plugins.abel.graph_release_doctor import (
    _identity_reasons,
    _probe_node_routes,
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

    mismatched = _identity_reasons(
        release,
        {
            "graph_id": "another-graph",
            "graph_version": "CausalNodeV4",
            "edge_set": "precision",
        },
    )
    missing = _identity_reasons(
        release,
        {
            "graph_id": "abel-main",
            "graph_version": "CausalNodeV4",
        },
    )

    assert any("graph_id" in reason and "another-graph" in reason for reason in mismatched)
    assert any("edge_set" in reason and "precision" in reason for reason in mismatched)
    assert any("edge_set" in reason and "<missing>" in reason for reason in missing)


def test_unfrozen_source_window_reaches_back_by_availability_lag():
    source_start, source_end, source_limit, visible_start, visible_end = (
        resolve_materialization_window(
            start="2024-01-03",
            end="2024-01-10",
            limit=20,
            config={},
            availability_lag_days=2,
        )
    )

    assert source_start == "2024-01-01"
    assert source_end == "2024-01-10"
    assert source_limit is None
    assert visible_start == "2024-01-03"
    assert visible_end == "2024-01-10"


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
