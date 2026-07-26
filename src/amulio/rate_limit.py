import asyncio
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Process-local request limiter for a single self-hosted aMulio instance."""

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                return False
            requests.append(now)
            return True
