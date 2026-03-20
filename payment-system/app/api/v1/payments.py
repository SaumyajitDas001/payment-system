"""
Payment API endpoints — production-ready.

Features:
  - Rate limiting on send endpoint (20 req/min)
  - Paginated transaction history with status filtering
  - Transaction detail lookup by ID
  - Consistent error responses via global handler
"""

from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.middleware.auth import get_current_user_id
from app.middleware.rate_limiter import payment_rate_limit
from app.schemas.payment import (
    PaymentRequest,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.payment_service import payment_service
from app.repositories.transaction_repo import transaction_repository
from app.repositories.wallet_repo import wallet_repository

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/send",
    response_model=TransactionResponse,
    status_code=201,
    dependencies=[Depends(payment_rate_limit)],
)
async def send_money(
    request: PaymentRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """
    Send money to another user.

    Requires an idempotency_key (UUID v4 recommended).
    Reuse the same key on retries to prevent duplicate charges.
    Rate limited to 20 requests per minute.
    """
    return await payment_service.send_money(db, user_id, request, redis_client)


@router.get("/history", response_model=TransactionListResponse)
async def get_transaction_history(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(
        default=None,
        description="Filter by status: PENDING, COMPLETED, FAILED",
    ),
):
    """
    Get paginated transaction history for the current user.
    Returns transactions where you are either the sender or receiver.
    Most recent transactions first.
    """
    wallet = await wallet_repository.get_by_user_id(db, user_id)
    if not wallet:
        return TransactionListResponse(
            transactions=[], total=0, page=page, page_size=page_size
        )

    transactions, total = await transaction_repository.get_by_wallet_id(
        db, wallet.id, page, page_size
    )

    return TransactionListResponse(
        transactions=[
            TransactionResponse.model_validate(t) for t in transactions
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single transaction by ID.
    Only accessible if you are the sender or receiver.
    """
    from sqlalchemy import select
    from app.models.transaction import Transaction
    from fastapi import HTTPException, status

    wallet = await wallet_repository.get_by_user_id(db, user_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    txn = result.scalar_one_or_none()

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Authorization: only sender or receiver can view
    if txn.sender_wallet_id != wallet.id and txn.receiver_wallet_id != wallet.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this transaction")

    return TransactionResponse.model_validate(txn)
