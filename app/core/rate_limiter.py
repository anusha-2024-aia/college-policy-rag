"""In-memory sliding-window rate limiter for sensitive authentication endpoints."""

from __future__ import annotations

import time
from collections import defaultdict
from fastapi import Request, HTTPException, status


class InMemoryRateLimiter:
    """Sliding-window rate limiter per client IP address."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, request: Request) -> None:
        """Enforce rate limit for client IP.

        Raises HTTPException(429) if client exceeds max_requests within window_seconds.
        """
        # Determine client identifier (IP address)
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "127.0.0.1")
        )

        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old timestamps
        history = [ts for ts in self._requests[client_ip] if ts > cutoff]
        self._requests[client_ip] = history

        if len(history) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - history[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Please retry after {retry_after} seconds.",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        self._requests[client_ip].append(now)

    def reset(self) -> None:
        """Clear rate limit store (useful for tests)."""
        self._requests.clear()


# Default rate limiter for login route: 10 requests per minute
login_rate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)

