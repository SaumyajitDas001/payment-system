"""
Payment schemas.
The idempotency_key is required on every payment request — no exceptions.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PaymentRequest(BaseModel):
    receiver_id: UUID
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)


class TransactionResponse(BaseModel):
    id: UUID
    sender_wallet_id: UUID
    receiver_wallet_id: UUID
    amount: Decimal
    currency: str
    status: str
    idempotency_key: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    page_size: int
