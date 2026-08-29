"""CAP date-cursor pagination contracts for exact node scalar series."""

import pytest

from abel_edge.plugins.abel.client import AbelClient
from abel_edge.plugins.abel.node_records_client import fetch_all_node_series


def test_fetch_node_series_partitions_cross_year_requests_and_resets_date_cursor():
    class StubSession:
        def __init__(self):
            self.bodies = []

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.bodies.append(json)
            body = json or {}
            start = body["start"]
            cursor = body.get("cursor_date")
            if start == "2025-01-01" and cursor is None:
                return StubResponse(
                    date="2025-01-01",
                    timestamp="2025-01-02T00:00:00Z",
                    has_more=True,
                )
            dates = {
                "2024-12-30": ("2024-12-31", "2025-01-01T00:00:00Z"),
                "2025-01-01": ("2025-01-02", "2025-01-03T00:00:00Z"),
                "2026-01-01": ("2026-01-01", "2026-01-02T00:00:00Z"),
            }
            date_value, timestamp = dates[start]
            return StubResponse(
                date=date_value,
                timestamp=timestamp,
                has_more=False,
            )

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, *, date, timestamp, has_more):
            self.date = date
            self.timestamp = timestamp
            self.has_more = has_more

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "mode": "node_series",
                "node": {"node_id": "catalog:test#1"},
                "data": [
                    {
                        "date": self.date,
                        "timestamp": self.timestamp,
                        "value": 1.0,
                    }
                ],
                "page": {
                    "has_more": self.has_more,
                    "max_date": self.date,
                },
            }

    session = StubSession()
    rows = AbelClient(session=session).fetch_node_series(
        node_id="catalog:test#1",
        start="2024-12-30",
        end="2026-01-02",
        limit=10,
        api_key="abel_test",
    )

    assert [row["timestamp"] for row in rows] == [
        "2025-01-01T00:00:00Z",
        "2025-01-02T00:00:00Z",
        "2025-01-03T00:00:00Z",
        "2026-01-02T00:00:00Z",
    ]
    assert session.bodies == [
        {
            "node_id": "catalog:test#1",
            "shape": "series",
            "start": "2024-12-30",
            "end": "2024-12-31",
            "limit": 10,
        },
        {
            "node_id": "catalog:test#1",
                "shape": "series",
                "start": "2025-01-01",
                "end": "2025-12-31",
                "limit": 10,
        },
        {
            "node_id": "catalog:test#1",
                "shape": "series",
                "start": "2025-01-01",
                "end": "2025-12-31",
                "limit": 10,
            "cursor_date": "2025-01-01",
        },
        {
            "node_id": "catalog:test#1",
                "shape": "series",
                "start": "2026-01-01",
                "end": "2026-01-02",
                "limit": 10,
        },
    ]


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
                "limit": 2,
            "cursor_date": "2026-05-01",
            "shape": "series",
        },
    ]


def test_limited_node_series_returns_trailing_rows_after_full_pagination():
    class StubSession:
        def __init__(self):
            self.bodies = []

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.bodies.append(json)
            cursor = (json or {}).get("cursor_date")
            if cursor is None:
                return StubResponse(days=(1, 2), has_more=True)
            return StubResponse(days=(3, 4), has_more=False)

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, *, days, has_more):
            self.days = days
            self.has_more = has_more

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "mode": "node_series",
                "node": {"node_id": "catalog:test#1"},
                "data": [
                    {
                        "timestamp": f"2026-05-{day:02d}T00:00:00Z",
                        "value": float(day),
                    }
                    for day in self.days
                ],
                "page": {
                    "has_more": self.has_more,
                    "max_date": f"2026-05-{max(self.days):02d}",
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

    assert [row["value"] for row in rows] == [3.0, 4.0]
    assert len(session.bodies) == 2


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


@pytest.mark.parametrize(
    "timestamp",
    ["2026-04-30T23:59:59Z", "2026-05-11T00:00:00Z"],
)
def test_fetch_node_series_rejects_rows_outside_active_window(timestamp):
    def fetch_page(**_kwargs):
        return {
            "mode": "node_series",
            "node": {"node_id": "catalog:test#1"},
            "data": [{"timestamp": timestamp, "value": 1.0}],
            "page": {"has_more": False},
        }

    with pytest.raises(ValueError, match="outside requested window"):
        fetch_all_node_series(
            fetch_page=fetch_page,
            node_id="catalog:test#1",
            start="2026-05-01",
            end="2026-05-10",
            limit=None,
            api_key="abel_test",
        )


def test_fetch_node_series_rejects_source_dates_outside_active_window():
    def fetch_page(**_kwargs):
        return {
            "mode": "node_series",
            "node": {"node_id": "catalog:test#1"},
            "data": [
                {
                    "date": "2026-04-30T00:00:00Z",
                    "timestamp": "2026-05-02T00:00:00Z",
                    "value": 1.0,
                }
            ],
            "page": {"has_more": False},
        }

    with pytest.raises(ValueError, match="source date .* outside requested window"):
        fetch_all_node_series(
            fetch_page=fetch_page,
            node_id="catalog:test#1",
            start="2026-05-01",
            end="2026-05-10",
            limit=None,
            api_key="abel_test",
        )
