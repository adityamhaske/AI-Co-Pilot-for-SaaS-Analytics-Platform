"""A real metrics overview for the sidebar.

The original UI showed `$48,250` MRR and `2.1%` churn as hardcoded literals beneath a
pulsing "Active DB Connected" badge. This endpoint exists so the interface can show that
strip honestly: every figure comes from the same metric registry the agent uses, so the
sidebar and the chat can never disagree.

Each tile also carries a short sparkline and a period-over-period delta, computed from
the same series — not a separate query that could drift.
"""

import datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.budget import spend_today
from app.core.config import settings
from app.core.rbac import get_current_user
from app.api.deps import tenant_scoped_db
from app.metrics import compiler, registry
from app.metrics.periods import build_periods
from app.metrics.schema import QueryShape
from app.providers import get_provider

router = APIRouter()
logger = structlog.get_logger()

# Metrics shown in the overview strip, in display order. Each must support a trend so a
# sparkline and a delta can be derived from one query.
OVERVIEW_METRICS = ("mrr", "active_users", "churn_rate", "new_signups")

SPARK_MONTHS = 6


class Tile(BaseModel):
    metric: str
    label: str
    unit: str
    value: float
    #: Fractional change against the previous period; null when there is no baseline.
    delta: float | None = None
    #: Recent values, oldest first, for a sparkline.
    spark: list[float] = Field(default_factory=list)


class Overview(BaseModel):
    tiles: list[Tile]
    generated_at: datetime.datetime
    #: Which model is answering questions, so the UI never has to guess.
    provider: str
    model: str
    #: Rolling 24-hour spend for this user, against the configured ceiling.
    spend_today_usd: float
    daily_limit_usd: float


def _month_starts(count: int) -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    start = today.replace(day=1)
    for _ in range(count - 1):
        start = (start - datetime.timedelta(days=1)).replace(day=1)
    return start, today


@router.get("", response_model=Overview)
def get_overview(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(tenant_scoped_db),
):
    tenant_id = current_user["tenant_id"]
    role = current_user["role"]

    start, end = _month_starts(SPARK_MONTHS)
    periods = build_periods(start, end, "month")

    tiles: list[Tile] = []
    for name in OVERVIEW_METRICS:
        try:
            metric = registry.get(name)
        except ValueError:
            continue

        # The overview respects the same role gate as the chat: a viewer does not see a
        # figure here that the agent would refuse to give them.
        if not metric.allowed_for(role):
            continue

        try:
            if metric.supports_shape(QueryShape.TREND):
                series = compiler.compute_series(db, name, tenant_id, periods)
            else:
                # churn_rate is snapshot-only; build its series period by period so the
                # sparkline still comes from the same definition.
                series = [
                    compiler.compute_value(db, name, tenant_id, period)
                    for period in periods
                ]
        except Exception as exc:
            logger.warning("overview_metric_failed", metric=name, error=str(exc))
            continue

        if not series:
            continue

        current = series[-1]
        previous = series[-2] if len(series) > 1 else None
        delta = None
        if previous:
            delta = round((current - previous) / abs(previous), 4)

        tiles.append(
            Tile(
                metric=name,
                label=metric.display_short,
                unit=metric.unit,
                value=compiler.format_value(metric, current),
                delta=delta,
                spark=[compiler.format_value(metric, v) for v in series],
            )
        )

    provider = get_provider()
    return Overview(
        tiles=tiles,
        generated_at=datetime.datetime.now(datetime.UTC),
        provider=provider.name,
        model=provider.model,
        spend_today_usd=round(spend_today(db, current_user["user_id"]), 4),
        daily_limit_usd=settings.daily_cost_limit_usd,
    )
