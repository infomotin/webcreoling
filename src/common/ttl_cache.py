"""
Tiny thread-safe TTL cache used by hot request paths.

Rationale: several read-mostly datasets (site configuration, ad slots, WAF
blocklists) were being re-queried on *every* HTTP request even though they
change at most a few times a day. This module keeps them in process memory
for a short, bounded window and provides explicit write-through invalidation
so admin edits are reflected immediately.

Design notes:
  * Values are produced outside the lock (producers may run slow SQL) and the
    cache is published atomically afterwards.
  * ``invalidate()`` must be called by every writer (repositories do this), so
    the TTL only bounds staleness for changes made by *other* processes.
  * Keys are plain strings; a change of process restarts with a cold cache.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

_LOCK = threading.Lock()
_STORE: Dict[str, Tuple[float, Any]] = {}

DEFAULT_TTL = 30.0


def cached(key: str, ttl: float, producer: Callable[[], Any]) -> Any:
    """Return the cached value for ``key``, recomputing it when older than ``ttl`` seconds."""
    with _LOCK:
        entry = _STORE.get(key)
        if entry is not None and (time.monotonic() - entry[0]) < ttl:
            return entry[1]

    # Produce outside the lock so one slow query never blocks other keys.
    value = producer()
    with _LOCK:
        _STORE[key] = (time.monotonic(), value)
    return value


def get(key: str, default: Any = None) -> Any:
    """Return a still-fresh value without recomputing; ``default`` when missing/expired is not checked (raw peek)."""
    with _LOCK:
        entry = _STORE.get(key)
    return entry[1] if entry is not None else default


def set(key: str, value: Any) -> Any:
    """Seed the cache with a known value (skips the producer entirely)."""
    with _LOCK:
        _STORE[key] = (time.monotonic(), value)
    return value


def invalidate(key: Optional[str] = None) -> None:
    """Drop one key, or the entire cache when ``key`` is None."""
    with _LOCK:
        if key is None:
            _STORE.clear()
        else:
            _STORE.pop(key, None)


def stats() -> Dict[str, Any]:
    """Diagnostic snapshot of cache contents (age per key)."""
    now = time.monotonic()
    with _LOCK:
        return {k: round(now - v[0], 3) for k, v in _STORE.items()}
