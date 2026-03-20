"""
Redis cache manager for the payment system.

CACHING STRATEGY: Write-Through Invalidation
  - READS: Check Redis first -> DB on miss -> populate cache from DB
  - WRITES: Always write to DB first -> invalidate Redis after commit
  - Never UPDATE the cache directly -- always invalidate and let the next read repopulate

WHY this strategy?
  - Cache-aside with invalidation is the safest pattern for financial data
  - If Redis dies, the system works (just slower) -- no data loss
  - If cache becomes stale, it self-heals on the next read
  - No write amplification: we delete one key instead of recomputing cached values

KEY SCHEMA:
  wallet:balance:{wallet_id}     -> Decimal string      (TTL: 5 min)
  wallet:info:{wallet_id}        -> JSON wallet object   (TTL: 10 min)
  idempotency:{key}              -> JSON response        (TTL: 24 hours)
  rate_limit:{user_id}:{endpoint} -> request count       (TTL: 1 min)
"""

import json
import logging
from decimal import Decimal
from uuid import UUID

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class CacheTTL:
    """Centralized TTL constants -- change in one place."""
    BALANCE = 300           # 5 minutes
    WALLET_INFO = 600       # 10 minutes
    IDEMPOTENCY = 86400     # 24 hours
    RATE_LIMIT = 60         # 1 minute


class CacheKeys:
    """
    Key naming conventions.
    Consistent prefixes make Redis monitoring and debugging easier.
    In production, you'd use these with Redis keyspace notifications.
    """

    @staticmethod
    def balance(wallet_id: UUID) -> str:
        return f"wallet:balance:{wallet_id}"

    @staticmethod
    def wallet_info(wallet_id: UUID) -> str:
        return f"wallet:info:{wallet_id}"

    @staticmethod
    def idempotency(key: str) -> str:
        return f"idempotency:{key}"

    @staticmethod
    def rate_limit(user_id: UUID, endpoint: str) -> str:
        return f"rate_limit:{user_id}:{endpoint}"


class RedisCacheManager:
    """
    All Redis operations go through this class.
    Every method has try/except -- Redis failure never crashes the app.
    """

    # ──────────────────────────────────────────────────────────
    #  BALANCE CACHE
    # ──────────────────────────────────────────────────────────

    async def get_balance(
        self, redis_client: aioredis.Redis, wallet_id: UUID
    ) -> Decimal | None:
        """
        Get cached balance. Returns None on miss or error.
        Caller should fall through to DB on None.
        """
        try:
            key = CacheKeys.balance(wallet_id)
            cached = await redis_client.get(key)
            if cached is not None:
                logger.debug("Cache HIT: balance for wallet %s", wallet_id)
                return Decimal(cached)
            logger.debug("Cache MISS: balance for wallet %s", wallet_id)
            return None
        except Exception as e:
            logger.warning("Redis get_balance error: %s", e)
            return None

    async def set_balance(
        self, redis_client: aioredis.Redis, wallet_id: UUID, balance: Decimal
    ) -> None:
        """Cache a balance after reading from DB."""
        try:
            key = CacheKeys.balance(wallet_id)
            await redis_client.setex(key, CacheTTL.BALANCE, str(balance))
        except Exception as e:
            logger.warning("Redis set_balance error: %s", e)

    async def invalidate_balance(
        self, redis_client: aioredis.Redis, wallet_id: UUID
    ) -> None:
        """Delete cached balance after a write operation."""
        try:
            key = CacheKeys.balance(wallet_id)
            await redis_client.delete(key)
            logger.debug("Cache INVALIDATED: balance for wallet %s", wallet_id)
        except Exception as e:
            logger.warning("Redis invalidate_balance error: %s", e)

    async def invalidate_balances_pipeline(
        self, redis_client: aioredis.Redis, wallet_ids: list[UUID]
    ) -> None:
        """
        Batch-invalidate multiple wallet balances using a Redis pipeline.
        Pipelines send all commands in one round-trip -- critical for
        payment processing where we invalidate sender + receiver.
        """
        try:
            pipe = redis_client.pipeline()
            for wid in wallet_ids:
                pipe.delete(CacheKeys.balance(wid))
            await pipe.execute()
            logger.debug(
                "Cache INVALIDATED (pipeline): %d wallets", len(wallet_ids)
            )
        except Exception as e:
            logger.warning("Redis pipeline invalidation error: %s", e)

    # ──────────────────────────────────────────────────────────
    #  WALLET INFO CACHE (full wallet object)
    # ──────────────────────────────────────────────────────────

    async def get_wallet_info(
        self, redis_client: aioredis.Redis, wallet_id: UUID
    ) -> dict | None:
        """Get cached wallet object (id, user_id, balance, currency, etc)."""
        try:
            key = CacheKeys.wallet_info(wallet_id)
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.warning("Redis get_wallet_info error: %s", e)
            return None

    async def set_wallet_info(
        self, redis_client: aioredis.Redis, wallet_id: UUID, wallet_data: dict
    ) -> None:
        """Cache full wallet object after DB read."""
        try:
            key = CacheKeys.wallet_info(wallet_id)
            await redis_client.setex(
                key, CacheTTL.WALLET_INFO, json.dumps(wallet_data, default=str)
            )
        except Exception as e:
            logger.warning("Redis set_wallet_info error: %s", e)

    async def invalidate_wallet_info(
        self, redis_client: aioredis.Redis, wallet_id: UUID
    ) -> None:
        try:
            await redis_client.delete(CacheKeys.wallet_info(wallet_id))
        except Exception as e:
            logger.warning("Redis invalidate_wallet_info error: %s", e)

    # ──────────────────────────────────────────────────────────
    #  IDEMPOTENCY CACHE
    # ──────────────────────────────────────────────────────────

    async def get_idempotency(
        self, redis_client: aioredis.Redis, key: str
    ) -> dict | None:
        """Check if an idempotency key has a cached response."""
        try:
            cache_key = CacheKeys.idempotency(key)
            cached = await redis_client.get(cache_key)
            if cached:
                logger.info("Idempotency HIT (Redis): %s", key)
                return json.loads(cached)
            return None
        except Exception as e:
            logger.warning("Redis get_idempotency error: %s", e)
            return None

    async def set_idempotency(
        self, redis_client: aioredis.Redis, key: str, response_data: dict
    ) -> None:
        """Store idempotency response after successful payment."""
        try:
            cache_key = CacheKeys.idempotency(key)
            await redis_client.setex(
                cache_key,
                CacheTTL.IDEMPOTENCY,
                json.dumps(response_data, default=str),
            )
        except Exception as e:
            logger.warning("Redis set_idempotency error: %s", e)

    # ──────────────────────────────────────────────────────────
    #  RATE LIMITING (bonus: production pattern)
    # ──────────────────────────────────────────────────────────

    async def check_rate_limit(
        self,
        redis_client: aioredis.Redis,
        user_id: UUID,
        endpoint: str,
        max_requests: int = 100,
    ) -> bool:
        """
        Sliding window rate limiter using Redis INCR + EXPIRE.
        Returns True if request is ALLOWED, False if rate-limited.

        This is how Stripe rate-limits API calls per API key.
        """
        try:
            key = CacheKeys.rate_limit(user_id, endpoint)
            current = await redis_client.incr(key)
            if current == 1:
                # First request in this window -- set expiry
                await redis_client.expire(key, CacheTTL.RATE_LIMIT)
            return current <= max_requests
        except Exception as e:
            logger.warning("Redis rate_limit error: %s", e)
            return True  # Fail open -- don't block users if Redis is down

    # ──────────────────────────────────────────────────────────
    #  HEALTH CHECK
    # ──────────────────────────────────────────────────────────

    async def is_healthy(self, redis_client: aioredis.Redis) -> bool:
        """Check Redis connectivity. Used by /health endpoint."""
        try:
            return await redis_client.ping()
        except Exception:
            return False


cache_manager = RedisCacheManager()
