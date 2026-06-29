import datetime
from typing import Literal
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from dateutil.relativedelta import relativedelta
from app.db.models import Customer, Subscription, Invoice, UsageEvent

# ---------------------------------------------------------------------------
# Pydantic v2 argument-validation models
# ---------------------------------------------------------------------------


class GetMetricTrendArgs(BaseModel):
    metric: Literal["mrr", "arr", "active_users", "new_signups"]
    start_date: datetime.date
    end_date: datetime.date
    granularity: Literal["day", "week", "month"] = "month"


class GetChurnRateArgs(BaseModel):
    period: Literal["last_month", "last_quarter", "last_year"]


class CompareSegmentsArgs(BaseModel):
    metric: Literal["mrr", "churn_rate", "active_users"]
    segment_a: str
    segment_b: str


class GetTopCustomersArgs(BaseModel):
    sort_by: Literal["mrr", "usage"] = "mrr"
    limit: int = 5

    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v: int) -> int:
        return max(1, min(25, v))


class ListActiveAlertsArgs(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


def get_metric_trend_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    try:
        args = GetMetricTrendArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for get_metric_trend: {e}")

    start_date = args.start_date
    end_date = args.end_date
    metric = args.metric

    if metric in ("mrr", "arr"):
        results = (
            db.query(
                func.strftime("%Y-%m", Subscription.start_date).label("month"),
                func.sum(Subscription.mrr).label("value"),
            )
            .filter(
                Subscription.tenant_id == tenant_id,
                Subscription.status == "active",
                Subscription.start_date >= start_date,
                Subscription.start_date <= end_date,
            )
            .group_by("month")
            .order_by("month")
            .limit(36)
            .all()
        )
        rows = [{"date": r.month, "value": round(float(r.value), 2)} for r in results]

    elif metric == "active_users":
        results = (
            db.query(
                func.strftime("%Y-%m", UsageEvent.timestamp).label("month"),
                func.count(func.distinct(UsageEvent.customer_id)).label("value"),
            )
            .filter(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.timestamp >= start_date,
                UsageEvent.timestamp <= end_date,
            )
            .group_by("month")
            .order_by("month")
            .limit(36)
            .all()
        )
        rows = [{"date": r.month, "value": int(r.value)} for r in results]

    elif metric == "new_signups":
        results = (
            db.query(
                func.strftime("%Y-%m", Customer.created_at).label("month"),
                func.count(Customer.id).label("value"),
            )
            .filter(
                Customer.tenant_id == tenant_id,
                Customer.created_at >= start_date,
                Customer.created_at <= end_date,
            )
            .group_by("month")
            .order_by("month")
            .limit(36)
            .all()
        )
        rows = [{"date": r.month, "value": int(r.value)} for r in results]

    else:
        rows = []

    if not rows:
        return [{"date": "no_data", "value": 0}]
    return rows


def get_churn_rate_handler(db: Session, tenant_id: str, kwargs: dict) -> dict:
    try:
        args = GetChurnRateArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for get_churn_rate: {e}")

    today = datetime.date.today()
    if args.period == "last_month":
        period_start = today - relativedelta(months=1)
    elif args.period == "last_quarter":
        period_start = today - relativedelta(months=3)
    else:  # last_year
        period_start = today - relativedelta(years=1)

    # Subscriptions canceled during this period
    churned_count: int = (
        db.query(func.count(Subscription.id))
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status == "canceled",
            Subscription.end_date >= period_start,
        )
        .scalar()
        or 0
    )

    # Subscriptions active at the start of the period
    active_at_start: int = (
        db.query(func.count(Subscription.id))
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.start_date <= period_start,
            or_(
                Subscription.end_date == None,  # noqa: E711
                Subscription.end_date >= period_start,
            ),
        )
        .scalar()
        or 0
    )

    churn_rate = (
        round(churned_count / active_at_start, 4) if active_at_start > 0 else 0.0
    )

    return {
        "period": args.period,
        "churn_rate": churn_rate,
        "churned_count": int(churned_count),
        "active_at_start": int(active_at_start),
    }


# --- Segment helper functions ---


def _segment_mrr(db: Session, tenant_id: str, customer_ids: list) -> float:
    if not customer_ids:
        return 0.0
    result = (
        db.query(func.sum(Subscription.mrr))
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.customer_id.in_(customer_ids),
            Subscription.status == "active",
        )
        .scalar()
    )
    return round(float(result), 2) if result else 0.0


def _segment_churn_rate(db: Session, tenant_id: str, customer_ids: list) -> float:
    if not customer_ids:
        return 0.0
    today = datetime.date.today()
    period_start = today - relativedelta(months=3)

    churned: int = (
        db.query(func.count(Subscription.id))
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.customer_id.in_(customer_ids),
            Subscription.status == "canceled",
            Subscription.end_date >= period_start,
        )
        .scalar()
        or 0
    )
    active: int = (
        db.query(func.count(Subscription.id))
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.customer_id.in_(customer_ids),
            Subscription.start_date <= period_start,
            or_(
                Subscription.end_date == None,  # noqa: E711
                Subscription.end_date >= period_start,
            ),
        )
        .scalar()
        or 0
    )
    return round(churned / active, 4) if active > 0 else 0.0


def _segment_active_users(db: Session, tenant_id: str, customer_ids: list) -> int:
    if not customer_ids:
        return 0
    today = datetime.date.today()
    month_ago = today - relativedelta(months=1)
    result = (
        db.query(func.count(func.distinct(UsageEvent.customer_id)))
        .filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.customer_id.in_(customer_ids),
            UsageEvent.timestamp >= month_ago,
        )
        .scalar()
    )
    return int(result) if result else 0


def compare_segments_handler(db: Session, tenant_id: str, kwargs: dict) -> dict:
    try:
        args = CompareSegmentsArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for compare_segments: {e}")

    def get_ids(segment_label: str) -> list:
        rows = (
            db.query(Customer.id)
            .filter(Customer.tenant_id == tenant_id, Customer.segment == segment_label)
            .all()
        )
        return [r.id for r in rows]

    ids_a = get_ids(args.segment_a)
    ids_b = get_ids(args.segment_b)

    if args.metric == "mrr":
        val_a = _segment_mrr(db, tenant_id, ids_a)
        val_b = _segment_mrr(db, tenant_id, ids_b)
    elif args.metric == "churn_rate":
        val_a = _segment_churn_rate(db, tenant_id, ids_a)
        val_b = _segment_churn_rate(db, tenant_id, ids_b)
    else:  # active_users
        val_a = _segment_active_users(db, tenant_id, ids_a)
        val_b = _segment_active_users(db, tenant_id, ids_b)

    return {
        "segment_a": {"name": args.segment_a, "value": val_a},
        "segment_b": {"name": args.segment_b, "value": val_b},
    }


def get_top_customers_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    try:
        args = GetTopCustomersArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for get_top_customers: {e}")

    limit = args.limit  # already clamped 1-25 by field_validator

    if args.sort_by == "mrr":
        results = (
            db.query(
                Customer.id,
                Customer.name,
                Customer.segment,
                func.sum(Subscription.mrr).label("mrr"),
            )
            .join(Subscription, Subscription.customer_id == Customer.id)
            .filter(
                Customer.tenant_id == tenant_id,
                Subscription.tenant_id == tenant_id,
                Subscription.status == "active",
            )
            .group_by(Customer.id, Customer.name, Customer.segment)
            .order_by(func.sum(Subscription.mrr).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "mrr": round(float(r.mrr), 2),
                "segment": r.segment,
            }
            for r in results
        ]

    else:  # usage
        results = (
            db.query(
                Customer.id,
                Customer.name,
                Customer.segment,
                func.count(UsageEvent.id).label("event_count"),
            )
            .join(UsageEvent, UsageEvent.customer_id == Customer.id)
            .filter(
                Customer.tenant_id == tenant_id,
                UsageEvent.tenant_id == tenant_id,
            )
            .group_by(Customer.id, Customer.name, Customer.segment)
            .order_by(func.count(UsageEvent.id).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "event_count": int(r.event_count),
                "segment": r.segment,
            }
            for r in results
        ]


def list_active_alerts_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    try:
        ListActiveAlertsArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for list_active_alerts: {e}")

    alerts = []
    today = datetime.date.today()
    seven_days_ago = today - datetime.timedelta(days=7)
    thirty_days_ago = today - datetime.timedelta(days=30)

    # Heuristic 1: usage spike — customer with most events in last 7 days
    spike = (
        db.query(
            Customer.name,
            func.count(UsageEvent.id).label("event_count"),
        )
        .join(UsageEvent, UsageEvent.customer_id == Customer.id)
        .filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.timestamp >= seven_days_ago,
        )
        .group_by(Customer.id, Customer.name)
        .order_by(func.count(UsageEvent.id).desc())
        .first()
    )
    if spike and spike.event_count > 20:
        alerts.append(
            {
                "type": "usage_spike",
                "customer_name": spike.name,
                "event_count": int(spike.event_count),
            }
        )

    # Heuristic 2: overdue invoices — unpaid, older than 30 days
    overdue_count: int = (
        db.query(func.count(Invoice.id))
        .filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status == "unpaid",
            Invoice.issue_date <= thirty_days_ago,
        )
        .scalar()
        or 0
    )
    if overdue_count > 0:
        alerts.append({"type": "overdue_invoices", "count": int(overdue_count)})

    if not alerts:
        return [{"type": "no_alerts", "message": "All clear"}]
    return alerts


# ---------------------------------------------------------------------------
# Dispatch table and execute_tool entry point
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "get_metric_trend": get_metric_trend_handler,
    "get_churn_rate": get_churn_rate_handler,
    "compare_segments": compare_segments_handler,
    "get_top_customers": get_top_customers_handler,
    "list_active_alerts": list_active_alerts_handler,
}


def execute_tool(db: Session, tenant_id: str, tool_name: str, tool_kwargs: dict):
    if tool_name not in TOOL_HANDLERS:
        raise ValueError(f"Unknown tool: {tool_name}")
    try:
        return TOOL_HANDLERS[tool_name](db, tenant_id, tool_kwargs)
    except ValueError:
        # Re-raise Pydantic validation errors and explicit raises as-is
        raise
    except Exception as e:
        raise RuntimeError(f"Tool execution error in '{tool_name}': {e}") from e
