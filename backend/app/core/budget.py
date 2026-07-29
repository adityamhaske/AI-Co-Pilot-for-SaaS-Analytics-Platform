"""Per-user spend metering and daily budgets.

Rate limiting alone does not bound cost: ten requests a minute can each drive several
tool-calling steps against a large context. This meters actual token spend and refuses
new requests once a user passes their daily ceiling.
"""

import uuid
from datetime import timedelta

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UsageRecord, utcnow

logger = structlog.get_logger()


def estimate_cost(
    input_tokens: int, output_tokens: int, provider: str | None = None
) -> float:
    """Dollar cost of a turn, priced for the provider that served it.

    Rates live in app/providers/PRICING so switching provider re-prices the budget
    automatically rather than silently metering against the wrong numbers.
    """
    from app.providers import pricing_for

    input_rate, output_rate = pricing_for(provider or settings.llm_provider)
    dollars = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return round(dollars, 6)


def spend_today(db: Session, user_id: str) -> float:
    since = utcnow() - timedelta(days=1)
    total = (
        db.query(func.sum(UsageRecord.cost_usd))
        .filter(UsageRecord.user_id == user_id, UsageRecord.created_at >= since)
        .scalar()
    )
    return float(total or 0.0)


def within_budget(db: Session, user_id: str) -> tuple[bool, float]:
    """Is the user under their rolling 24-hour ceiling?"""
    spent = spend_today(db, user_id)
    return spent < settings.daily_cost_limit_usd, spent


def record(
    db: Session,
    tenant_id: str,
    user_id: str,
    input_tokens: int,
    output_tokens: int,
    conversation_id: str | None = None,
) -> UsageRecord:
    entry = UsageRecord(
        id=f"use_{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=estimate_cost(input_tokens, output_tokens),
    )
    db.add(entry)
    db.commit()
    logger.info(
        "usage_recorded",
        user_id=user_id,
        tenant_id=tenant_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=entry.cost_usd,
    )
    return entry
