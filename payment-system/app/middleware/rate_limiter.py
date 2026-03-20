"""
Rate limiting middleware using Redis.

Different endpoints get different limits:
  - Balance check: 200 req/min (users refresh a lot)
  - Send payment: 20 req/min (prevents rapid-fire transfers)
  - Register: 5 req/min (prevents spam accounts)

Uses the cache_manager's sliding window counter.
"""

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
import redis.asyncio as aioredis

from app.core.redis import get_redis
from app.services.cache_manager import cache_manager


class RateLimiter:
    """
    Configurable rate limiter. Use as a FastAPI dependency.

    Usage:
        @router.get("/balance", dependencies=[Depends(RateLimiter(max_requests=200))])
        async def get_balance(...):
    """

    def __init__(self, max_requests: int = 100):
        self.max_requests = max_requests

    async def __call__(
        self,
        request: Request,
        redis_client: aioredis.Redis = Depends(get_redis),
    ):
        # Extract user ID from the request state (set by auth middleware)
        # For unauthenticated endpoints, use the client IP
        user_id = getattr(request.state, "user_id", None)
        identifier = str(user_id) if user_id else request.client.host

        endpoint = request.url.path
        allowed = await cache_manager.check_rate_limit(
            redis_client,
            identifier,  # type: ignore
            endpoint,
            self.max_requests,
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: max {self.max_requests} requests per minute",
                headers={"Retry-After": "60"},
            )


# Pre-configured rate limiters for common use
payment_rate_limit = RateLimiter(max_requests=20)
balance_rate_limit = RateLimiter(max_requests=200)
auth_rate_limit = RateLimiter(max_requests=5)
