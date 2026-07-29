from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api import api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import RequestContextMiddleware, configure_logging
from app.db.session import engine
from app.metrics import registry

configure_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loading the registry here turns a malformed metric definition into a failed
    # startup rather than a 500 the first time someone asks a question.
    metrics = registry.all_metrics()
    logger.info(
        "startup",
        environment=settings.environment,
        metrics=sorted(metrics),
        max_agent_steps=settings.max_agent_steps,
    )
    yield
    logger.info("shutdown")


app = FastAPI(
    title="SaaS Analytics AI Co-Pilot",
    version="0.3.0",
    lifespan=lifespan,
    # The interactive docs expose the full tool surface; keep them out of production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Conversation-Id"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["ops"])
def health_check():
    """Liveness: the process is up. Deliberately does not touch the database."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def readiness_check():
    """Readiness: the process can actually serve traffic.

    Separate from /health so a database blip takes the instance out of the load-balancer
    rotation without the orchestrator killing and restarting a healthy process.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("readiness_failed", error=str(exc))
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "ready", "database": "ok"}


@app.get("/", tags=["ops"])
def read_root():
    return {
        "name": "SaaS Analytics AI Co-Pilot API",
        "version": app.version,
        "docs_url": app.docs_url,
        "health_check": "/health",
    }
