"""
Wallet schemas.
Balance is returned as a string to avoid floating-point serialization issues in JSON.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class WalletCreate(BaseModel):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class WalletResponse(BaseModel):
    id: UUID
    user_id: UUID
    balance: Decimal
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletTopUp(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=2)
