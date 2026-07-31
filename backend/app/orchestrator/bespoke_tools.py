"""Tools that are not metric readings, and still carry hand-written SQL.

Metric readings — trends, snapshots, segment comparisons — live in the declarative
registry in ``app/metrics``, where one YAML definition drives the tool schema, the
argument validation and the SQL together. What remains here is a customer ranking and a
set of alerting heuristics: neither is "the value of a metric over a period", so neither
fits the registry's shape.

This file used to be called ``app/validator/query_validator.py``, a name it had long
outgrown — it contained no validation, only business SQL. Removing the metric handlers
also removed three separate definitions of MRR that lived here: a point-in-time sum for
trends, and two ``status == 'active'`` variants for segment comparison and ranking. They
disagreed, so "MRR trend" and "compare MRR by segment" returned numbers that could not
be reconciled.

Anything added here should be a candidate for the registry first. Hand-written SQL is the
exception, not the default.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Customer, Invoice, Subscription, UsageEvent

# Usage-event count above which a customer is flagged as spiking, over a 7-day window.
USAGE_SPIKE_THRESHOLD = 20
# Invoices unpaid for longer than this are considered overdue.
OVERDUE_INVOICE_DAYS = 30


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
    thirty_days_ago = today - datetime.timedelta(days=OVERDUE_INVOICE_DAYS)

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
    if spike and spike.event_count > USAGE_SPIKE_THRESHOLD:
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


BESPOKE_HANDLERS = {
    "get_top_customers": get_top_customers_handler,
    "list_active_alerts": list_active_alerts_handler,
}
