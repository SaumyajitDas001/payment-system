"""
Wallet repository.
The update_balance method implements optimistic locking via the version column.
If version doesn't match, 0 rows are updated → caller knows to retry.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet


class WalletRepository:

    async def get_by_user_id(self, db: AsyncSession, user_id: UUID) -> Wallet | None:
        result = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, wallet_id: UUID) -> Wallet | None:
        result = await db.execute(
            select(Wallet).where(Wallet.id == wallet_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, db: AsyncSession, wallet_id: UUID) -> Wallet | None:
        """
        SELECT ... FOR UPDATE — acquires a row-level lock.
        Used during payment processing to prevent concurrent modifications.
        """
        result = await db.execute(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, wallet: Wallet) -> Wallet:
        db.add(wallet)
        await db.flush()
        return wallet

    async def update_balance(
        self,
        db: AsyncSession,
        wallet_id: UUID,
        new_balance: Decimal,
        expected_version: int,
    ) -> bool:
        """
        Optimistic lock update: only succeeds if version matches.
        Returns True if update applied, False if version conflict.
        """
        result = await db.execute(
            update(Wallet)
            .where(Wallet.id == wallet_id, Wallet.version == expected_version)
            .values(balance=new_balance, version=expected_version + 1)
        )
        return result.rowcount > 0


wallet_repository = WalletRepository()
