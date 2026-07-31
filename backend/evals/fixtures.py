"""A deterministic dataset with hand-computed expected answers.

Every date is derived from *today*, so the expected values stay correct as the calendar
moves. That is what lets the eval dataset assert real numbers without being rewritten
every month.

Layout, all subscriptions starting 400 days ago:

    enterprise   5 customers x $1,000 MRR   active
    smb          3 customers x   $200 MRR   active
    midmarket    2 customers x   $500 MRR   cancelled 40 days ago

So, as of today:

    mrr                 5,600      (5,000 enterprise + 600 smb)
    arr                67,200      (5,600 x 12)
    enterprise mrr      5,000
    smb mrr               600
    churn (quarter)      0.2       (2 of 10 subscriptions active at quarter start)
"""

import datetime

from sqlalchemy.orm import Session

from app.db.models import Customer, Invoice, Subscription, Tenant, UsageEvent

EVAL_TENANT = "tenant_eval"

TODAY = datetime.date.today()
SUB_START = TODAY - datetime.timedelta(days=400)
CHURN_DATE = TODAY - datetime.timedelta(days=40)

COHORTS = [
    ("ent", "enterprise", 5, 1000.0, None),
    ("smb", "smb", 3, 200.0, None),
    ("mid", "midmarket", 2, 500.0, CHURN_DATE),
]

# Hand-computed from the layout above. The eval dataset references these by name.
EXPECTED = {
    "mrr": 5600.0,
    "arr": 67200.0,
    "enterprise_mrr": 5000.0,
    "smb_mrr": 600.0,
    "midmarket_mrr": 0.0,  # cancelled, so no current MRR
    "churn_rate_quarter": 0.2,
    "total_customers": 10,
    "active_subscriptions": 8,
}


def build(db: Session, tenant_id: str = EVAL_TENANT) -> None:
    """Create (or recreate) the deterministic eval dataset."""
    wipe(db, tenant_id)

    db.add(Tenant(id=tenant_id, name="Eval Tenant"))
    # Flush the tenant before the rows that reference it. Customer and Subscription carry
    # a raw ForeignKey with no ORM relationship, so SQLAlchemy has no mapper dependency to
    # order the inserts by. This passed only while SQLite left foreign keys unenforced.
    db.flush()

    for prefix, segment, count, mrr, end_date in COHORTS:
        for i in range(count):
            customer_id = f"{tenant_id}_{prefix}_{i}"
            db.add(
                Customer(
                    id=customer_id,
                    tenant_id=tenant_id,
                    name=f"{segment.title()} Customer {i + 1}",
                    segment=segment,
                    created_at=datetime.datetime.combine(SUB_START, datetime.time.min),
                )
            )
            db.add(
                Subscription(
                    id=f"sub_{customer_id}",
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    mrr=mrr,
                    start_date=SUB_START,
                    end_date=end_date,
                    status="canceled" if end_date else "active",
                )
            )
            # A paid and an unpaid invoice each, the unpaid one old enough to be overdue.
            db.add(
                Invoice(
                    id=f"inv_paid_{customer_id}",
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    amount=mrr,
                    issue_date=TODAY - datetime.timedelta(days=15),
                    status="paid",
                )
            )
            if prefix == "ent":
                db.add(
                    Invoice(
                        id=f"inv_unpaid_{customer_id}",
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        amount=mrr,
                        issue_date=TODAY - datetime.timedelta(days=45),
                        status="unpaid",
                    )
                )
            # Usage: enterprise customers are heavier users, giving top-N a stable order.
            events = 30 if prefix == "ent" else 5
            for e in range(events):
                db.add(
                    UsageEvent(
                        id=f"evt_{customer_id}_{e}",
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        event_type="login",
                        timestamp=datetime.datetime.combine(
                            TODAY - datetime.timedelta(days=e % 20), datetime.time.min
                        ),
                    )
                )

    db.commit()


def wipe(db: Session, tenant_id: str = EVAL_TENANT) -> None:
    for model in (UsageEvent, Invoice, Subscription, Customer):
        db.query(model).filter(model.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
    db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
    db.commit()
