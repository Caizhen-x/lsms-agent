"""In-process per-user rate limit.

Two sliding-window buckets per identifier: hour and day.  Reset semantics are
"drop events older than the window," not "tick at the top of the hour" — this
prevents bursts at boundaries.

Storage is a dict in memory.  On HF Space restart, counters reset.  That's
fine for v0; this limits damage from a leaked password without claiming to be
a hardened denial-of-service guard.

Configurable via env:
  RATE_LIMIT_HOUR (default 30)
  RATE_LIMIT_DAY  (default 200)
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

HOUR_LIMIT = int(os.getenv("RATE_LIMIT_HOUR", "30"))
DAY_LIMIT = int(os.getenv("RATE_LIMIT_DAY", "200"))

_HOUR_SEC = 3600
_DAY_SEC = 86400


@dataclass
class _UserState:
    hour: deque[float]
    day: deque[float]


class RateLimiter:
    def __init__(self, hour_limit: int = HOUR_LIMIT, day_limit: int = DAY_LIMIT) -> None:
        self.hour_limit = hour_limit
        self.day_limit = day_limit
        self._lock = threading.Lock()
        self._states: dict[str, _UserState] = defaultdict(lambda: _UserState(deque(), deque()))

    def _prune(self, dq: deque[float], now: float, window: int) -> None:
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def check_and_consume(self, identifier: str) -> tuple[bool, str]:
        """Return (allowed, message).  message is a user-facing explanation when denied."""
        now = time.time()
        with self._lock:
            st = self._states[identifier or "unknown"]
            self._prune(st.hour, now, _HOUR_SEC)
            self._prune(st.day, now, _DAY_SEC)

            if len(st.day) >= self.day_limit:
                wait_s = int(_DAY_SEC - (now - st.day[0]))
                return False, (
                    f"Daily limit reached ({self.day_limit} turns / 24 h). "
                    f"Try again in ~{wait_s // 3600}h {(wait_s % 3600) // 60}m."
                )
            if len(st.hour) >= self.hour_limit:
                wait_s = int(_HOUR_SEC - (now - st.hour[0]))
                return False, (
                    f"Hourly limit reached ({self.hour_limit} turns / hour). "
                    f"Try again in ~{wait_s // 60}m."
                )
            st.hour.append(now)
            st.day.append(now)
            return True, ""


# Module-level singleton — one bucket store for the whole process.
rate_limiter = RateLimiter()
