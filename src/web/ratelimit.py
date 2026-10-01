"""Minimal in-process fixed-window rate limiting for credential endpoints.

Kept deliberately dependency-free: only failed authentication attempts (and a
handful of expensive OTP/delivery requests) are counted, so legitimate users
and the automated test suite are unaffected while brute-force and OTP-spam
runs are bounded.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

_LOCK = threading.Lock()
_WINDOWS: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)


def _prune(key: Tuple[str, str], window: float, now: float) -> Deque[float]:
    hits = _WINDOWS[key]
    while hits and (now - hits[0]) > window:
        hits.popleft()
    return hits


def record(scope: str, identity: str) -> None:
    """Count one hit against ``scope`` for ``identity``."""
    key = (scope, identity)
    now = time.monotonic()
    with _LOCK:
        _prune(key, _WINDOW.get(scope, 300.0), now).append(now)


def blocked(scope: str, identity: str) -> bool:
    """True when ``identity`` already exhausted ``scope``'s allowance."""
    key = (scope, identity)
    now = time.monotonic()
    limit, window = _LIMITS.get(scope, (10, 300.0))
    with _LOCK:
        return len(_prune(key, window, now)) >= limit


def allow(scope: str, identity: str) -> bool:
    """Count one hit and report whether the caller is still within limits."""
    key = (scope, identity)
    now = time.monotonic()
    limit, window = _LIMITS.get(scope, (10, 300.0))
    with _LOCK:
        hits = _prune(key, window, now)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def reset(scope: str, identity: str) -> None:
    """Clear recorded hits (called after a successful authentication)."""
    with _LOCK:
        _WINDOWS.pop((scope, identity), None)


def clear_all() -> None:
    """Drop every recorded hit (test helper)."""
    with _LOCK:
        _WINDOWS.clear()


# scope -> (max hits, window seconds)
_LIMITS: Dict[str, Tuple[int, float]] = {
    "auth.login.failures": (10, 300.0),
    "auth.otp.request": (20, 600.0),
    "auth.forgot.request": (5, 600.0),
    "auth.register.request": (10, 600.0),
}
_WINDOW = {scope: window for scope, (_, window) in _LIMITS.items()}
