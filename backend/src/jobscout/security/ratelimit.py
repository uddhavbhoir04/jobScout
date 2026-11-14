"""Small in-memory sliding-window rate limiter for login / sign-up (brute force + spam sign-ups).

In-memory is enough for one API process. With several processes or servers, move this to Redis
(same interface) so the counts are shared.
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> float:
        """Record one attempt. Returns 0 if allowed, else seconds until the next attempt is allowed."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, q[0] + window_s - now)
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory: drop keys with no recent attempts
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - 3600]:
                    del self._hits[k]
            return 0.0

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()

# (attempts, window seconds)
LOGIN_PER_ACCOUNT = (10, 15 * 60)   # wrong-password guesses against one email
LOGIN_PER_IP = (50, 15 * 60)        # one client trying many emails
REGISTER_PER_IP = (10, 60 * 60)     # sign-ups from one client
