"""
Redis connection management.
Uses redis-py with hiredis parser for maximum throughput.
Connection pool is shared across the application.
"""

import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()

redis_client = redis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,  # Return strings, not bytes
)


async def get_redis() -> redis.Redis:
    """FastAPI dependency for Redis access."""
    return redis_client
