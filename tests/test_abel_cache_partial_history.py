"""Regression coverage for Abel bars with naturally short histories."""

import pandas as pd

from abel_edge.engine.adapter_registry import AbelDataFeedAdapter, FeedLoadRequest
from abel_edge.engine.cache import cache_entry_for_request


def test_abel_bars_adapter_does_not_rewrite_probed_partial_end_cache(tmp_path, monkeypatch):
    calls = []

    def fake_fetch_bars(*, symbols, start=None, end=None, **_kwargs):
        calls.append({"symbols": symbols, "start": start, "end": end})
        return pd.DataFrame(
            {
                "timestamp": ["2020-01-02T00:00:00Z", "2020-01-03T00:00:00Z"],
                "symbol": ["AAPL", "AAPL"],
                "open": [99.0, 100.0],
                "high": [101.0, 102.0],
                "low": [98.0, 99.0],
                "close": [100.0, 101.0],
                "volume": [1000.0, 1100.0],
            }
        )

    import abel_edge.plugins.abel.prices as prices_module

    monkeypatch.setattr(prices_module, "fetch_bars", fake_fetch_bars)
    request = FeedLoadRequest(
        adapter="abel",
        kind="bars",
        symbol="AAPL",
        field=None,
        timeframe="1d",
        start="2020-01-01",
        end="2020-02-01",
        limit=10,
        profile="daily",
        options={"cache_root": str(tmp_path)},
        strategy_id=None,
        feed_name="primary",
    )
    entry = cache_entry_for_request(
        adapter="abel",
        symbol="AAPL",
        timeframe="1d",
        profile="daily",
        options=request.options,
        cache_root=tmp_path,
    )

    first = AbelDataFeedAdapter().load(request)
    metadata_after_first_load = entry.meta_path.read_bytes()
    second = AbelDataFeedAdapter().load(request)

    assert len(calls) == 1
    assert entry.meta_path.read_bytes() == metadata_after_first_load
    pd.testing.assert_frame_equal(second, first)
