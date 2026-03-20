"""
Structured logging configuration.

Production systems need machine-parseable logs (JSON) for log aggregation
tools like Datadog, ELK Stack, or CloudWatch. Development needs human-readable logs.

Every log line includes: timestamp, level, service, request_id, user_id.
The request_id is injected by middleware so you can trace a single request
across all service calls — essential for debugging payment failures.
"""

import logging
import json
import sys
from datetime import datetime, timezone
from contextvars import ContextVar

from app.core.config import get_settings

settings = get_settings()

# Context variables — set per-request by middleware, available everywhere
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="anonymous")


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for production.
    Every log line is a valid JSON object — perfect for log aggregation.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.app_name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get("-"),
            "user_id": user_id_ctx.get("anonymous"),
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_ctx.get("-")[:8]
        uid = user_id_ctx.get("anon")[:8]
        return (
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} "
            f"| {record.levelname:<8} "
            f"| rid={rid} uid={uid} "
            f"| {record.module}.{record.funcName} "
            f"| {record.getMessage()}"
        )


def setup_logging():
    """Configure logging based on environment."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if settings.debug:
        handler.setFormatter(DevFormatter())
    else:
        handler.setFormatter(JSONFormatter())

    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
