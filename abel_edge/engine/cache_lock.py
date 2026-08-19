"""Small cross-process lock used for atomic cache publication."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_cache_lock(
    data_path: Path,
    *,
    timeout_seconds: float = 30.0,
    stale_seconds: float = 300.0,
) -> Iterator[None]:
    """Serialize publication of one cache entry across threads and processes."""

    lock_path = data_path.parent / f".lock-{data_path.stem[:16]}"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileNotFoundError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out creating cache lock: {lock_path}") from exc
            time.sleep(0.05)
            continue
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > stale_seconds
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for cache lock: {lock_path}")
            time.sleep(0.05)
            continue
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        finally:
            os.close(descriptor)
        break
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
