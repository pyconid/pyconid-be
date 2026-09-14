from fnmatch import fnmatch
from typing import Callable, Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.rate_limiter.key_builder import RateLimitKeyBuilder
from core.rate_limiter.memory import InMemoryRateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting with secure key generation"""

    def __init__(
        self,
        app,
        backend: type[InMemoryRateLimiter],
        backend_kwargs: Optional[dict] = None,
        enabled: bool = True,
        limit: int = 100,
        window: int = 60,
        key_func: Optional[Callable[[Request], str]] = None,
        exclude_paths: Optional[list[str]] = None,
        use_fingerprint: bool = True,
    ):
        """
        Initialize rate limit middleware

        Args:
            app: FastAPI application
            backend: InMemoryRateLimiter
            backend_kwargs: Configuration passed to the backend constructor
            enabled: Enable/disable rate limiting
            limit: Maximum requests per window
            window: Time window in seconds
            key_func: Custom function to extract rate limit key (optional)
            exclude_paths: List of paths to exclude from rate limiting
            use_fingerprint: Use browser fingerprint for anonymous users (more secure)
        """
        super().__init__(app)
        self.backend = backend(**(backend_kwargs or {}))
        self.enabled = enabled
        self.limit = limit
        self.window = window
        self.key_func = key_func
        self.exclude_paths = exclude_paths or []
        self.use_fingerprint = use_fingerprint

    def _get_rate_limit_key(self, request: Request) -> str:
        """
        Get rate limit key using secure key builder

        If custom key_func is provided, use it.
        Otherwise, use secure RateLimitKeyBuilder.
        """
        if self.key_func:
            return self.key_func(request)

        return RateLimitKeyBuilder.build_key(
            request, use_fingerprint=self.use_fingerprint
        )

    def _should_exclude(self, path: str) -> bool:
        """
        Check if path should be excluded from rate limiting.

        Supports:
        - exact prefix match (old behavior)
        - glob patterns like '/user-profile/*/profile-picture/'
        """
        normalized_path = path.rstrip("/") or "/"

        for exclude_path in self.exclude_paths:
            pattern = exclude_path.rstrip("/") or "/"

            if any(ch in pattern for ch in ["*", "?", "["]):
                if fnmatch(normalized_path, pattern):
                    return True
            else:
                if normalized_path.startswith(pattern):
                    return True

        return False

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting"""
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for excluded paths
        if self._should_exclude(request.url.path):
            return await call_next(request)

        # Get rate limit key
        key = self._get_rate_limit_key(request)

        # Check rate limit
        is_allowed, retry_after = await self.backend.is_allowed(
            key, self.limit, self.window
        )

        if not is_allowed:
            # Rate limit exceeded
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "message": "Rate limit exceeded",
                },
                headers={
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                    "Retry-After": str(int(retry_after or 0)),
                },
            )

        # Process request
        response = await call_next(request)

        # Get remaining requests AFTER processing (accurate count)
        remaining = await self.backend.get_remaining(key, self.limit)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self.window)

        return response
