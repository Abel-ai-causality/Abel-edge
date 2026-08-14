"""Request-boundary tests for Abel day_bar symbol and node modes."""

import pytest
import requests

from abel_edge.plugins.abel.client import AbelClient


def test_day_bar_request_preserves_exchange_suffixes():
    class StubResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    class StubSession:
        def __init__(self):
            self.body = None

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.body = json
            return StubResponse()

    session = StubSession()
    AbelClient(session=session).fetch_bars(
        symbols=["605138.SS", "001395.SZ", "9606.HK", "XFLI.TO"],
        start="2020-01-01",
        end="2026-05-28",
        timeframe="1d",
        limit=200_000,
        fields=["close"],
        api_key="test",
    )

    assert session.body["symbols"] == [
        "605138.SS",
        "001395.SZ",
        "9606.HK",
        "XFLI.TO",
    ]


def test_fetch_node_series_uses_exact_single_node_id_mode():
    class StubSession:
        def __init__(self):
            self.calls = []

        def post(self, url, json=None, headers=None, timeout=20):
            self.calls.append(
                {"url": url, "json": json, "headers": headers, "timeout": timeout}
            )
            return StubResponse(
                {
                    "data": [
                        {
                            "timestamp": "2026-05-01T00:00:00Z",
                            "node_id": "v4::catalog::demo",
                            "value": 1.25,
                        }
                    ]
                }
            )

    class StubResponse:
        status_code = 200
        headers = {}

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    session = StubSession()
    rows = AbelClient(session=session).fetch_node_series(
        node_id="v4::catalog::demo",
        start="2026-05-01",
        end="2026-05-10",
        limit=20,
        api_key="abel_test",
    )

    assert rows[0]["value"] == 1.25
    assert session.calls[0]["url"] == "https://cap.abel.ai/api/market/day_bar"
    assert session.calls[0]["json"] == {
        "node_id": "v4::catalog::demo",
        "start": "2026-05-01",
        "end": "2026-05-10",
        "limit": 20,
    }
    assert "symbols" not in session.calls[0]["json"]
    assert "fields" not in session.calls[0]["json"]


def test_fetch_bars_never_sends_node_id_mode_fields():
    class StubSession:
        def __init__(self):
            self.body = None

        def post(self, _url, *, json=None, headers=None, timeout=None):
            self.body = json
            return StubResponse()

    class StubResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    session = StubSession()
    AbelClient(session=session).fetch_bars(
        symbols=["000001.SZ"],
        start="2026-05-01",
        end="2026-05-10",
        timeframe="1d",
        limit=20,
        fields=["close"],
        api_key="abel_test",
    )

    assert session.body["symbols"] == ["000001.SZ"]
    assert "node_id" not in session.body


def test_fetch_node_series_does_not_fallback_to_symbol_mode_on_404():
    class StubSession:
        def __init__(self):
            self.calls = []

        def post(self, url, json=None, headers=None, timeout=20):
            self.calls.append(json)
            return StubResponse()

    class StubResponse:
        status_code = 404
        headers = {}

        def raise_for_status(self):
            raise requests.HTTPError("CausalNodeV4 node not found")

    session = StubSession()
    client = AbelClient(session=session)

    with pytest.raises(requests.HTTPError, match="node not found"):
        client.fetch_node_series(
            node_id="v4::missing",
            start="2026-05-01",
            end="2026-05-10",
            limit=20,
            api_key="abel_test",
        )

    assert session.calls == [
        {
            "node_id": "v4::missing",
            "start": "2026-05-01",
            "end": "2026-05-10",
            "limit": 20,
        }
    ]
