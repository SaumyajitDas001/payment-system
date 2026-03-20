"""
Application entry point — production-ready.

Wires together:
  - Structured logging (JSON in prod, readable in dev)
  - Request context middleware (request_id tracing)
  - Global exception handlers (consistent error responses)
  - CORS middleware
  - All API routes
  - Health check with dependency status
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.logging_config import setup_logging
from app.core.redis import redis_client
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.services.cache_manager import cache_manager

settings = get_settings()

# Initialize structured logging BEFORE anything else
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    logger.info("Starting %s...", settings.app_name)

    redis_ok = await cache_manager.is_healthy(redis_client)
    if redis_ok:
        logger.info("Redis connected")
    else:
        logger.warning("Redis unavailable — running without cache")

    yield

    logger.info("Shutting down...")
    await redis_client.close()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Real-time payment processing system with idempotent transactions",
    lifespan=lifespan,
)

# Order matters: outermost middleware runs first
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register global exception handlers
register_exception_handlers(app)

# Mount API routes
app.include_router(api_router)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check for load balancers and orchestration."""
    redis_ok = await cache_manager.is_healthy(redis_client)
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": "1.0.0",
        "dependencies": {
            "redis": "connected" if redis_ok else "disconnected",
        },
    }
