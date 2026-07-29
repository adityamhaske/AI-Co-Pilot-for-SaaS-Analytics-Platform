"""Structured logging.

`structlog` was imported in one module and never configured, so it fell back to a
print-shaped default: no timestamps, no levels, no correlation, and nothing a log
aggregator could parse. This configures it once at startup — JSON in production so it
can be ingested, human-readable colours in development.

A request-id is bound to a context variable at the edge, so every log line emitted while
handling a request carries it without being threaded through call signatures.
"""

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"

# Paths that would otherwise fill the log with health-check noise.
QUIET_PATHS = {"/health", "/"}


def configure_logging() -> None:
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id (and the caller, once known) to the logging context."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an upstream id so a trace survives across services.
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id

        if request.url.path not in QUIET_PATHS:
            structlog.get_logger().info(
                "request_completed", status_code=response.status_code
            )

        return response
