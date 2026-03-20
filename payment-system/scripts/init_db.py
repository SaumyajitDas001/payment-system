"""
Quick database initialization script.
Creates all tables directly from ORM models.
For production, use Alembic migrations instead.

Usage: python -m scripts.init_db
"""

import asyncio

from app.core.database import Base, engine
from app.models import User, Wallet, Transaction  # noqa: F401 — triggers model registration


async def init_db():
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())
