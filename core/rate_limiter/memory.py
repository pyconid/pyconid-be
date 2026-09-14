import asyncio
import time
from collections import OrderedDict
from typing import Dict, List, Optional


class InMemoryRateLimiter:
    """In-memory rate limiter using a bounded sliding-window store."""

    def __init__(
        self,
        max_keys: int = 10_000,
        cleanup_interval: int = 60,
    ):
        if max_keys < 1:
            raise ValueError("max_keys must be greater than zero")
        if cleanup_interval < 1:
            raise ValueError("cleanup_interval must be greater than zero")

        self._requests: Dict[str, List[float]] = OrderedDict()
        self._max_keys = max_keys
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()
        self._lock = asyncio.Lock()

    def _cleanup_expired(self, cutoff_time: float) -> None:
        expired_keys = []
        for key, timestamps in self._requests.items():
            valid_timestamps = [ts for ts in timestamps if ts > cutoff_time]
            if valid_timestamps:
                self._requests[key] = valid_timestamps
            else:
                expired_keys.append(key)

        for key in expired_keys:
            del self._requests[key]

    def _evict_if_needed(self) -> None:
        while len(self._requests) > self._max_keys:
            self._requests.popitem(last=False)

    def _maybe_cleanup(self, current_time: float, window: int) -> None:
        if current_time - self._last_cleanup >= self._cleanup_interval:
            self._cleanup_expired(current_time - window)
            self._last_cleanup = current_time

    async def is_allowed(
        self, key: str, limit: int, window: int
    ) -> tuple[bool, Optional[int]]:
        """
        Check if request is allowed using sliding window algorithm

        Args:
            key: Unique identifier for the rate limit
            limit: Maximum number of requests allowed
            window: Time window in seconds

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        async with self._lock:
            current_time = time.time()
            cutoff_time = current_time - window
            self._maybe_cleanup(current_time, window)

            timestamps = [ts for ts in self._requests.get(key, []) if ts > cutoff_time]
            if timestamps:
                self._requests[key] = timestamps
            else:
                self._requests.pop(key, None)

            # Check if under limit
            if len(timestamps) < limit:
                timestamps.append(current_time)
                self._requests[key] = timestamps
                self._requests.move_to_end(key)
                self._evict_if_needed()
                return True, None

            # Calculate retry_after
            if timestamps:
                oldest_request = timestamps[0]
                retry_after = window - (current_time - oldest_request)
            else:
                # Edge case: limit is 0, no requests stored
                retry_after = window

            return False, max(0, retry_after)

    async def reset(self, key: str) -> None:
        """Reset rate limit for a key"""
        async with self._lock:
            if key in self._requests:
                del self._requests[key]

    async def get_remaining(self, key: str, limit: int) -> int:
        """Get remaining requests for a key"""
        async with self._lock:
            timestamps = self._requests.get(key)
            if timestamps:
                self._requests.move_to_end(key)
            current_count = len(timestamps or [])
            return max(0, limit - current_count)

    async def cleanup_expired(self, window: int) -> None:
        """
        Cleanup expired entries to prevent memory bloat
        Should be called periodically by a background task
        """
        async with self._lock:
            current_time = time.time()
            self._cleanup_expired(current_time - window)
            self._last_cleanup = current_time
