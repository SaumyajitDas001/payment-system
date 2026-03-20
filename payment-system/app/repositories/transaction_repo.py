"""
Transaction repository.
Supports querying by wallet (for history) and by idempotency key (for dedup).
"""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction


class TransactionRepository:

    async def create(self, db: AsyncSession, txn: Transaction) -> Transaction:
        db.add(txn)
        await db.flush()
        return txn

    async def get_by_idempotency_key(
        self, db: AsyncSession, key: str
    ) -> Transaction | None:
        result = await db.execute(
            select(Transaction).where(Transaction.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_wallet_id(
        self,
        db: AsyncSession,
        wallet_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Transaction], int]:
        """Returns paginated transactions for a wallet (as sender or receiver)."""
        base_query = select(Transaction).where(
            or_(
                Transaction.sender_wallet_id == wallet_id,
                Transaction.receiver_wallet_id == wallet_id,
            )
        )

        # Count total
        count_result = await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        # Fetch page
        offset = (page - 1) * page_size
        result = await db.execute(
            base_query
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        transactions = list(result.scalars().all())

        return transactions, total


transaction_repository = TransactionRepository()
