from fastapi import APIRouter

from app.api.v1.users import router as users_router
from app.api.v1.wallets import router as wallets_router
from app.api.v1.payments import router as payments_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(users_router)
api_router.include_router(wallets_router)
api_router.include_router(payments_router)
