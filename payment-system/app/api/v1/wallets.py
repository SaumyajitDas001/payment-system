"""
Wallet API endpoints.
All routes are protected — require a valid JWT.
"""

from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.middleware.auth import get_current_user_id
from app.schemas.wallet import WalletResponse, WalletTopUp
from app.services.wallet_service import wallet_service

router = APIRouter(prefix="/wallets", tags=["Wallets"])


@router.get("/me", response_model=WalletResponse)
async def get_my_wallet(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Get current user's wallet and balance."""
    return await wallet_service.get_wallet(db, user_id, redis_client)


@router.post("/me/top-up", response_model=WalletResponse)
async def top_up_wallet(
    data: WalletTopUp,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Add funds to current user's wallet."""
    return await wallet_service.top_up(db, user_id, data.amount, redis_client)
