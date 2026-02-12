"""Simple in-memory TTL cache for computed metrics."""

from __future__ import annotations

import time
from typing import Any


class MetricsCache:
    """Thread-unsafe dict + monotonic clock TTL cache."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value or ``None`` if missing / expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with current timestamp."""
        self._store[key] = (time.monotonic(), value)

    def invalidate(self, key: str) -> None:
        """Remove a single key (no-op if absent)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop all entries."""
        self._store.clear()
