"""
Application configuration.
All settings loaded from environment variables with sensible defaults.
pydantic-settings validates types at startup — bad config crashes fast, not at 3am.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "PaymentSystem"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://payment_user:payment_pass@localhost:5432/payment_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Idempotency
    idempotency_key_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — parsed once, reused everywhere."""
    return Settings()
