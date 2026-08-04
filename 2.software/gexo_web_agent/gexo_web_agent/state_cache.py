"""Thread-safe controller state cache.

The transport thread (rclpy spin or mock ticker) calls `update()`; the asyncio
web thread calls `get()` / `is_stale()`.  The whole snapshot is replaced
atomically under a lock, so readers never observe torn state.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .schemas import StateData, now_ms


class StateCache:
    def __init__(self, stale_timeout_s: float = 1.0) -> None:
        self._lock = threading.Lock()
        self._stale_timeout_s = float(stale_timeout_s)
        self._state: Optional[StateData] = None
        self._received_monotonic: Optional[float] = None
        self._received_wall_ms: Optional[int] = None

    def update(self, state: StateData) -> None:
        with self._lock:
            self._state = state
            self._received_monotonic = time.monotonic()
            self._received_wall_ms = now_ms()

    def get(self) -> Optional[StateData]:
        with self._lock:
            return self._state

    def last_update_ms(self) -> Optional[int]:
        with self._lock:
            return self._received_wall_ms

    def age_s(self) -> Optional[float]:
        """Seconds since last update; None if no state was ever received."""
        with self._lock:
            if self._received_monotonic is None:
                return None
            return time.monotonic() - self._received_monotonic

    def is_stale(self) -> bool:
        """True when no state was ever received OR the last one is too old."""
        age = self.age_s()
        return age is None or age > self._stale_timeout_s

    def has_state(self) -> bool:
        return self.get() is not None
