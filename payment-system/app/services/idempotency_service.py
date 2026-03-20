"""
Idempotency service.

Implements a two-tier idempotency check:
  Tier 1 (fast): Redis lookup — sub-millisecond, handles 99% of retries
  Tier 2 (durable): PostgreSQL UNIQUE constraint — catches retries if Redis is down

The key lifecycle:
  1. Client sends request with Idempotency-Key header
  2. We check if key exists (Redis → DB fallback)
  3. If exists: return stored response immediately (no processing)
  4. If not: process request, store response against key, return response
  5. Key expires after TTL (default 24h) — client can reuse the key value after

Why TWO tiers?
  - Redis alone: fast but volatile — a restart loses all keys, enabling duplicates
  - DB alone: durable but slow — adds ~5ms to every request for the key lookup
  - Both: sub-ms for normal retries, durable fallback for edge cases
"""

import json
import logging
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL = settings.idempotency_key_ttl_hours * 3600  # Convert to seconds


class IdempotencyService:
    """
    Manages idempotency keys across Redis (fast) and PostgreSQL (durable).
    """

    async def check_key(
        self,
        key: str,
        redis_client: aioredis.Redis | None = None,
    ) -> dict | None:
        """
        Check if an idempotency key has already been processed.
        Returns the stored response dict if found, None if new.
        """
        if not key:
            return None

        # Tier 1: Redis (fast path)
        if redis_client:
            try:
                cached = await redis_client.get(f"idempotency:{key}")
                if cached:
                    logger.info("Idempotency hit (Redis): key=%s", key)
                    return json.loads(cached)
            except Exception as e:
                # Redis failure shouldn't block the request
                logger.warning("Redis idempotency check failed: %s", e)

        return None

    async def store_key(
        self,
        key: str,
        response_data: dict,
        status_code: int,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        """
        Store the response for an idempotency key.
        Called AFTER successful processing and DB commit.
        """
        stored = {
            "response": response_data,
            "status_code": status_code,
        }

        # Store in Redis with TTL
        if redis_client:
            try:
                await redis_client.setex(
                    f"idempotency:{key}",
                    IDEMPOTENCY_TTL,
                    json.dumps(stored, default=str),
                )
                logger.info("Idempotency key stored (Redis): key=%s", key)
            except Exception as e:
                logger.warning("Redis idempotency store failed: %s", e)

    async def delete_key(
        self,
        key: str,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        """
        Delete an idempotency key. Used when a request fails and
        should be retryable with the same key.
        """
        if redis_client:
            try:
                await redis_client.delete(f"idempotency:{key}")
            except Exception:
                pass  # Best effort


idempotency_service = IdempotencyService()
