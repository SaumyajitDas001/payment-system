"""
Request context middleware.

Generates a unique request_id for every incoming request and makes it
available to all downstream code via contextvars. This lets you grep
a single request across thousands of log lines.

Also injects the request_id into the response headers so the client
can reference it in bug reports: "My payment failed, request_id is abc-123."
"""

import uuid
import time
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging_config import request_id_ctx, user_id_ctx

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate unique request ID
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_ctx.set(rid)

        # Extract user_id from auth token if present (set by auth dependency)
        user_id_ctx.set("anonymous")

        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "Request failed: %s %s -> %s (%.1fms)",
                request.method, request.url.path, type(e).__name__, elapsed,
            )
            raise

        elapsed = (time.perf_counter() - start) * 1000

        # Add request_id to response headers
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time-Ms"] = f"{elapsed:.1f}"

        # Log request completion
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )

        return response
