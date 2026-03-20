"""
Global exception handler.

Converts all exceptions into consistent JSON error responses.
In production, this prevents stack traces from leaking to clients
while still logging the full error internally.

Every error response includes:
  - error: machine-readable error code
  - detail: human-readable message
  - request_id: for customer support correlation
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging_config import request_id_ctx

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI):
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": _status_to_error_code(exc.status_code),
                "detail": exc.detail,
                "request_id": request_id_ctx.get("-"),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Simplify validation errors for the client
        errors = []
        for error in exc.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            errors.append({"field": field, "message": error["msg"]})

        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": "Request validation failed",
                "errors": errors,
                "request_id": request_id_ctx.get("-"),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Log the full traceback internally
        logger.error(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )

        # Return sanitized error to client (no stack trace)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "An unexpected error occurred. Please try again.",
                "request_id": request_id_ctx.get("-"),
            },
        )


def _status_to_error_code(status_code: int) -> str:
    """Map HTTP status codes to machine-readable error codes."""
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        402: "insufficient_funds",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
    }
    return mapping.get(status_code, "unknown_error")
