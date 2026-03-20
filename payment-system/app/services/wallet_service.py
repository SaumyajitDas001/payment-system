"""
Wallet service — enhanced with full Redis cache integration.

READ PATH (get_balance):
  1. Check Redis for cached balance
  2. Cache HIT  -> return immediately (0.2ms)
  3. Cache MISS -> read from PostgreSQL (5ms) -> populate cache -> return

WRITE PATH (top_up, transfer):
  1. Write to PostgreSQL (source of truth)
  2. AFTER commit -> invalidate Redis cache
  3. Next read will repopulate cache from fresh DB data

This is the Cache-Aside pattern with write-through invalidation.
"""

from decimal import Decimal
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import OptimisticLockException, WalletNotFoundException
from app.repositories.wallet_repo import wallet_repository
from app.schemas.wallet import WalletResponse
from app.services.cache_manager import cache_manager

MAX_TOPUP_RETRIES = 3


class WalletService:

    async def get_wallet(
        self,
        db: AsyncSession,
        user_id: UUID,
        redis_client: aioredis.Redis | None = None,
    ) -> WalletResponse:
        """
        Get wallet with Redis-accelerated balance lookup.
        The full wallet object is always read from DB (it's infrequent).
        The balance specifically is cached because it's checked constantly.
        """
        wallet = await wallet_repository.get_by_user_id(db, user_id)
        if not wallet:
            raise WalletNotFoundException()

        # Try to serve balance from cache
        if redis_client:
            cached_balance = await cache_manager.get_balance(
                redis_client, wallet.id
            )
            if cached_balance is not None:
                # Cache hit: use cached balance but fresh wallet metadata
                wallet.balance = cached_balance
            else:
                # Cache miss: populate cache for next time
                await cache_manager.set_balance(
                    redis_client, wallet.id, wallet.balance
                )

        return WalletResponse.model_validate(wallet)

    async def get_balance_fast(
        self,
        db: AsyncSession,
        user_id: UUID,
        redis_client: aioredis.Redis | None = None,
    ) -> Decimal:
        """
        Fastest possible balance check.
        Used internally by services that just need the number.
        """
        if redis_client:
            # First: try cache
            wallet = await wallet_repository.get_by_user_id(db, user_id)
            if not wallet:
                raise WalletNotFoundException()

            cached = await cache_manager.get_balance(redis_client, wallet.id)
            if cached is not None:
                return cached

            # Cache miss: read from DB and cache
            await cache_manager.set_balance(
                redis_client, wallet.id, wallet.balance
            )
            return wallet.balance

        # No Redis: straight to DB
        wallet = await wallet_repository.get_by_user_id(db, user_id)
        if not wallet:
            raise WalletNotFoundException()
        return wallet.balance

    async def top_up(
        self,
        db: AsyncSession,
        user_id: UUID,
        amount: Decimal,
        redis_client: aioredis.Redis | None = None,
    ) -> WalletResponse:
        """
        Add funds to wallet with optimistic locking and cache invalidation.
        Retries on version conflicts (up to MAX_TOPUP_RETRIES).
        """
        for attempt in range(1, MAX_TOPUP_RETRIES + 1):
            wallet = await wallet_repository.get_by_user_id(db, user_id)
            if not wallet:
                raise WalletNotFoundException()

            new_balance = wallet.balance + amount
            updated = await wallet_repository.update_balance(
                db, wallet.id, new_balance, wallet.version
            )

            if updated:
                await db.commit()

                # CRITICAL: Invalidate AFTER commit, not before
                # If we invalidate before commit and the commit fails,
                # the cache is empty but the old balance is still in DB.
                # Next read would cache the old value -- correct behavior.
                # But if we invalidate after commit, the next read caches
                # the NEW value -- which is what we want.
                if redis_client:
                    await cache_manager.invalidate_balance(
                        redis_client, wallet.id
                    )
                    await cache_manager.invalidate_wallet_info(
                        redis_client, wallet.id
                    )

                await db.refresh(wallet)
                return WalletResponse.model_validate(wallet)

            # Version conflict: rollback and retry
            await db.rollback()

            if attempt == MAX_TOPUP_RETRIES:
                raise OptimisticLockException()

        raise OptimisticLockException()


wallet_service = WalletService()
