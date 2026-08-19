"""Cross-process cache publication lock behavior."""

from __future__ import annotations

import os

from abel_edge.engine.cache_lock import exclusive_cache_lock


def test_cache_lock_retries_transient_missing_lock_path(tmp_path, monkeypatch):
    real_open = os.open
    attempts = 0
    observed_paths = []

    def transient_open(path, flags, mode=0o777):
        nonlocal attempts
        attempts += 1
        observed_paths.append(path)
        if attempts == 1:
            raise FileNotFoundError(path)
        return real_open(path, flags, mode)

    monkeypatch.setattr("abel_edge.engine.cache_lock.os.open", transient_open)

    with exclusive_cache_lock(tmp_path / "series.csv"):
        assert attempts == 2
    assert observed_paths[-1].name == ".lock-series"
