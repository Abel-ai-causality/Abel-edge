"""CAP date-cursor pagination contracts for exact node scalar series."""

import pytest

from abel_edge.plugins.abel.client import AbelClient


def test_fetch_node_series_follows_cap_date_cursor_pages_without_losing_rows():
    class StubSession:
        def __init__(self):
            self.bodies = []

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.bodies.append(json)
            if len(self.bodies) == 1:
                return StubResponse(
                    data=[
                        {
                            "date": "2026-05-01",
                            "timestamp": "2026-05-01T00:00:00Z",
                            "value": 1.0,
                        }
                    ],
                    max_date="2026-05-01",
                    has_more=True,
                )
            return StubResponse(
                data=[
                    {
                        "date": "2026-05-02",
                        "timestamp": "2026-05-02T00:00:00Z",
                        "value": 2.0,
                    }
                ],
                max_date="2026-05-02",
                has_more=False,
            )

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, *, data, max_date, has_more):
            self.data = data
            self.max_date = max_date
            self.has_more = has_more

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "mode": "node_series",
                "node": {"node_id": "catalog:test#1", "feature": "value"},
                "data": self.data,
                "page": {
                    "limit": 2,
                    "max_date": self.max_date,
                    "has_more": self.has_more,
                },
            }

    session = StubSession()
    rows = AbelClient(session=session).fetch_node_series(
        node_id="catalog:test#1",
        start="2026-05-01",
        end="2026-05-10",
        limit=2,
        api_key="abel_test",
    )

    assert [row["date"] for row in rows] == ["2026-05-01", "2026-05-02"]
    assert session.bodies == [
        {
            "node_id": "catalog:test#1",
            "start": "2026-05-01",
            "end": "2026-05-10",
            "limit": 2,
            "shape": "series",
        },
        {
            "node_id": "catalog:test#1",
            "start": "2026-05-01",
            "end": "2026-05-10",
            "limit": 1,
            "cursor_date": "2026-05-01",
            "shape": "series",
        },
    ]


def test_fetch_node_series_rejects_duplicate_utc_timestamps_across_pages():
    class StubSession:
        def __init__(self):
            self.calls = 0

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.calls += 1
            return StubResponse(cursor=self.calls, has_more=self.calls == 1)

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, *, cursor, has_more):
            self.cursor = cursor
            self.has_more = has_more

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "mode": "node_series",
                "node": {"node_id": "catalog:test#1"},
                "data": [
                    {
                        "timestamp": "2026-05-01T00:00:00Z",
                        "value": float(self.cursor),
                    }
                ],
                "page": {
                    "has_more": self.has_more,
                    "max_date": f"2026-05-0{self.cursor}",
                },
            }

    with pytest.raises(ValueError, match="duplicate UTC timestamp"):
        AbelClient(session=StubSession()).fetch_node_series(
            node_id="catalog:test#1",
            start="2026-05-01",
            end="2026-05-10",
            limit=2,
            api_key="abel_test",
        )


def test_fetch_node_series_rejects_stalled_cap_date_cursor():
    class StubSession:
        def __init__(self):
            self.calls = 0

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.calls += 1
            return StubResponse(call=self.calls)

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, *, call):
            self.call = call

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "mode": "node_series",
                "node": {"node_id": "catalog:test#1"},
                "data": [
                    {
                        "date": f"2026-05-0{self.call}",
                        "timestamp": f"2026-05-0{self.call}T00:00:00Z",
                        "value": float(self.call),
                    }
                ],
                "page": {"has_more": True, "max_date": "2026-05-01"},
            }

    with pytest.raises(ValueError, match="date cursor did not advance"):
        AbelClient(session=StubSession()).fetch_node_series(
            node_id="catalog:test#1",
            start="2026-05-01",
            end="2026-05-10",
            limit=3,
            api_key="abel_test",
        )
