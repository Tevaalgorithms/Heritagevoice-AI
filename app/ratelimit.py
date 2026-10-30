"""A small sliding-window rate limiter, kept in memory.

It protects the open (no sign-in) endpoints from being hammered. It is per process, which is
enough for one server; behind several servers each would count separately.
"""

import time
from collections import deque
from collections.abc import Callable

MAX_KEYS = 10_000


class SlidingWindowLimiter:
    """Allows `limit` calls per `window_s` seconds for each key."""

    def __init__(
        self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Count this call and say whether it is within the limit."""
        now = self._clock()
        calls = self._calls.setdefault(key, deque())
        self._expire(calls, now)
        if len(calls) >= self._limit:
            return False
        calls.append(now)
        self._trim()
        return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until the oldest counted call leaves the window (at least 1)."""
        calls = self._calls.get(key)
        if not calls:
            return 1
        return max(1, int(calls[0] + self._window - self._clock()) + 1)

    def _expire(self, calls: deque[float], now: float) -> None:
        while calls and calls[0] <= now - self._window:
            calls.popleft()

    def _trim(self) -> None:
        """Keep memory bounded: forget the oldest keys if there are too many."""
        while len(self._calls) > MAX_KEYS:
            self._calls.pop(next(iter(self._calls)))
