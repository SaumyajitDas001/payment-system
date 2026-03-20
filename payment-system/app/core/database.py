"""
Database connection management.
Uses SQLAlchemy 2.0 async engine with connection pooling.
Pool settings are tuned for a payment system: limited connections, aggressive recycling.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,          # Max persistent connections
    max_overflow=10,       # Burst connections beyond pool_size
    pool_timeout=30,       # Seconds to wait for a connection from pool
    pool_recycle=1800,     # Recycle connections every 30 min (prevents stale connections)
    pool_pre_ping=True,    # Test connection health before using it
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit — avoids lazy-load surprises
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields a database session.
    Session is automatically closed after the request, even on exceptions.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
