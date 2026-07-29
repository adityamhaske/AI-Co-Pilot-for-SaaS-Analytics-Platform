import datetime
from typing import Literal

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.db.models import Customer, Invoice, Subscription, UsageEvent

# A trend is built from one conditional aggregate per period, so the period count is
# bounded to keep the generated SQL sane. 400 covers a year of daily points or three
# decades of monthly ones.
MAX_PERIODS = 400

# Months per year, used to derive ARR from MRR.
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Pydantic v2 argument-validation models
# ---------------------------------------------------------------------------


class GetMetricTrendArgs(BaseModel):
    metric: Literal["mrr", "arr", "active_users", "new_signups"]
    start_date: datetime.date
    end_date: datetime.date
    granularity: Literal["day", "week", "month"] = "month"

    @model_validator(mode="after")
    def check_range(self) -> "GetMetricTrendArgs":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be earlier than start_date")
        return self


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


Period = tuple[str, datetime.date, datetime.date]


def _build_periods(
    start: datetime.date, end: datetime.date, granularity: str
) -> list[Period]:
    """Split [start, end] into (label, period_start, period_end_exclusive) buckets.

    Building the period spine in Python keeps the SQL free of dialect-specific date
    functions. The previous implementation used ``strftime``, which exists only in
    SQLite — so every trend query raised ``UndefinedFunction`` on the PostgreSQL that
    the deployment guide recommends.
    """
    periods: list[Period] = []

    if granularity == "month":
        cursor = start.replace(day=1)
        step = lambda d: d + relativedelta(months=1)  # noqa: E731
        label = lambda d: d.strftime("%Y-%m")  # noqa: E731
    elif granularity == "week":
        cursor = start - datetime.timedelta(days=start.weekday())  # ISO Monday
        step = lambda d: d + datetime.timedelta(days=7)  # noqa: E731
        label = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731
    else:  # day
        cursor = start
        step = lambda d: d + datetime.timedelta(days=1)  # noqa: E731
        label = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731

    while cursor <= end:
        nxt = step(cursor)
        periods.append((label(cursor), cursor, nxt))
        cursor = nxt
        if len(periods) > MAX_PERIODS:
            raise ValueError(
                f"That range needs more than {MAX_PERIODS} {granularity} buckets. "
                "Narrow the date range or use a coarser granularity."
            )

    return periods


def get_metric_trend_handler(db: Session, tenant_id: str, kwargs: dict) -> list:
    try:
        args = GetMetricTrendArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for get_metric_trend: {e}") from e

    periods = _build_periods(args.start_date, args.end_date, args.granularity)
    if not periods:
        return []

    if args.metric in ("mrr", "arr"):
        # MRR is a point-in-time measure: every subscription that is live during a period
        # contributes its full MRR to that period. The previous query grouped by
        # start_date, which measured *new* MRR booked in each month and dropped a
        # subscription from every period after the one it started in.
        columns = [
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Subscription.start_date < period_end)
                            & (
                                or_(
                                    Subscription.end_date.is_(None),
                                    Subscription.end_date >= period_start,
                                )
                            ),
                            Subscription.mrr,
                        ),
                        else_=0.0,
                    )
                ),
                0.0,
            ).label(f"p{i}")
            for i, (_, period_start, period_end) in enumerate(periods)
        ]
        row = db.query(*columns).filter(Subscription.tenant_id == tenant_id).one()

        # ARR is annualised MRR. It used to return the MRR series unchanged.
        multiplier = MONTHS_PER_YEAR if args.metric == "arr" else 1
        return [
            {"date": label, "value": round(float(row[i] or 0.0) * multiplier, 2)}
            for i, (label, _, _) in enumerate(periods)
        ]

    if args.metric == "active_users":
        columns = [
            func.count(
                func.distinct(
                    case(
                        (
                            (UsageEvent.timestamp >= period_start)
                            & (UsageEvent.timestamp < period_end),
                            UsageEvent.customer_id,
                        ),
                    )
                )
            ).label(f"p{i}")
            for i, (_, period_start, period_end) in enumerate(periods)
        ]
        row = db.query(*columns).filter(UsageEvent.tenant_id == tenant_id).one()
        return [
            {"date": label, "value": int(row[i] or 0)}
            for i, (label, _, _) in enumerate(periods)
        ]

    # new_signups
    columns = [
        func.count(
            case(
                (
                    (Customer.created_at >= period_start)
                    & (Customer.created_at < period_end),
                    Customer.id,
                ),
            )
        ).label(f"p{i}")
        for i, (_, period_start, period_end) in enumerate(periods)
    ]
    row = db.query(*columns).filter(Customer.tenant_id == tenant_id).one()
    return [
        {"date": label, "value": int(row[i] or 0)}
        for i, (label, _, _) in enumerate(periods)
    ]


def get_churn_rate_handler(db: Session, tenant_id: str, kwargs: dict) -> dict:
    try:
        args = GetChurnRateArgs.model_validate(kwargs)
    except Exception as e:
        raise ValueError(f"Invalid arguments for get_churn_rate: {e}") from e

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
        raise ValueError(f"Invalid arguments for compare_segments: {e}") from e

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
        raise ValueError(f"Invalid arguments for get_top_customers: {e}") from e

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
        raise ValueError(f"Invalid arguments for list_active_alerts: {e}") from e

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
            # Both sides are scoped to the tenant. Filtering only the event side relied on
            # customer IDs never colliding across tenants — true today, but the kind of
            # implicit assumption that turns into a cross-tenant leak after a schema change.
            Customer.tenant_id == tenant_id,
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
