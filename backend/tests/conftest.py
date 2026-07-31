import os

# Must be set before app.core.config.Settings() is instantiated at import time below,
# so the fail-fast JWT_SECRET validation doesn't require a real secret in test runs.
os.environ.setdefault("ENVIRONMENT", "test")

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.db.models import Customer, Subscription, Tenant, UsageEvent, User
from app.db.session import Base, enforce_sqlite_foreign_keys, get_db
from app.main import app

# The suite defaults to SQLite for speed, but honours DATABASE_URL so the same tests can
# be pointed at PostgreSQL. This matters: it was hardcoded to SQLite, which meant a CI
# job that set DATABASE_URL to Postgres would silently keep testing SQLite and prove
# nothing about the dialect the production database actually uses.
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test_override.db")

engine = enforce_sqlite_foreign_keys(
    create_engine(
        SQLALCHEMY_DATABASE_URL,
        # check_same_thread is a SQLite-only argument and errors on any other driver.
        connect_args=(
            {"check_same_thread": False}
            if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
            else {}
        ),
    )
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear rate-limit counters between tests.

    Every test shares one TestClient source address, so without this the 5/minute login
    limit leaks across tests and whichever ones happen to run later fail. Tests that
    deliberately exercise rate limiting still can — they just start from a clean slate.
    """
    from app.core.limiter import limiter

    storage = getattr(limiter, "_storage", None)
    if storage is not None and hasattr(storage, "reset"):
        storage.reset()
    yield


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    del app.dependency_overrides[get_db]


@pytest.fixture
def test_user(db_session):
    # Ensure tenant exists
    tenant = db_session.query(Tenant).filter(Tenant.id == "tenant_test").first()
    if not tenant:
        tenant = Tenant(id="tenant_test", name="Test Tenant")
        db_session.add(tenant)
        db_session.commit()

    user = db_session.query(User).filter(User.email == "test@test.com").first()
    if not user:
        user = User(
            id="user_test",
            tenant_id=tenant.id,
            email="test@test.com",
            hashed_password=get_password_hash("password123"),
            role="viewer",
        )
        db_session.add(user)
        db_session.commit()
    return user


# ---------------------------------------------------------------------------
# Metric fixtures
#
# A hand-built dataset with known answers, so metric tests assert exact numbers:
#
#     sub_a  Alpha (enterprise)  mrr=100  2026-01-01 -> open ended
#     sub_b  Beta  (smb)         mrr=200  2026-02-01 -> 2026-03-15 (cancelled)
#
# Expected closing MRR by month: Jan 100, Feb 300, Mar 100, Apr 100. March drops back
# because sub_b cancelled on the 15th and MRR is measured as of the end of the period.
# A third subscription worth 9999 sits in another tenant and must never appear.
# ---------------------------------------------------------------------------

TENANT = "tenant_metrics"
OTHER_TENANT = "tenant_other"

D = datetime.date
DT = datetime.datetime


@pytest.fixture
def metrics_data(db_session):
    for tid in (TENANT, OTHER_TENANT):
        if not db_session.query(Tenant).filter(Tenant.id == tid).first():
            db_session.add(Tenant(id=tid, name=tid))
    # Flush the tenants before adding rows that reference them. Customer and Subscription
    # carry a raw ForeignKey with no ORM relationship, so SQLAlchemy has no mapper-level
    # dependency to sort on and may emit the child insert first.
    db_session.flush()

    db_session.add_all(
        [
            Customer(
                id="cust_a",
                tenant_id=TENANT,
                name="Alpha",
                segment="enterprise",
                created_at=DT(2026, 1, 5),
            ),
            Customer(
                id="cust_b",
                tenant_id=TENANT,
                name="Beta",
                segment="smb",
                created_at=DT(2026, 2, 10),
            ),
            Subscription(
                id="sub_a",
                tenant_id=TENANT,
                customer_id="cust_a",
                mrr=100.0,
                start_date=D(2026, 1, 1),
                end_date=None,
                status="active",
            ),
            Subscription(
                id="sub_b",
                tenant_id=TENANT,
                customer_id="cust_b",
                mrr=200.0,
                start_date=D(2026, 2, 1),
                end_date=D(2026, 3, 15),
                status="canceled",
            ),
            Customer(
                id="cust_x",
                tenant_id=OTHER_TENANT,
                name="Xeno",
                segment="enterprise",
                created_at=DT(2026, 1, 5),
            ),
            Subscription(
                id="sub_x",
                tenant_id=OTHER_TENANT,
                customer_id="cust_x",
                mrr=9999.0,
                start_date=D(2026, 1, 1),
                end_date=None,
                status="active",
            ),
            UsageEvent(
                id="evt_a1",
                tenant_id=TENANT,
                customer_id="cust_a",
                event_type="login",
                timestamp=DT(2026, 1, 10),
            ),
            UsageEvent(
                id="evt_a2",
                tenant_id=TENANT,
                customer_id="cust_a",
                event_type="login",
                timestamp=DT(2026, 1, 11),
            ),
            UsageEvent(
                id="evt_b1",
                tenant_id=TENANT,
                customer_id="cust_b",
                event_type="login",
                timestamp=DT(2026, 2, 3),
            ),
            UsageEvent(
                id="evt_x1",
                tenant_id=OTHER_TENANT,
                customer_id="cust_x",
                event_type="login",
                timestamp=DT(2026, 1, 10),
            ),
        ]
    )
    db_session.commit()
    yield db_session

    for model, ids in (
        (UsageEvent, ["evt_a1", "evt_a2", "evt_b1", "evt_x1"]),
        (Subscription, ["sub_a", "sub_b", "sub_x"]),
        (Customer, ["cust_a", "cust_b", "cust_x"]),
        (Tenant, [TENANT, OTHER_TENANT]),
    ):
        if ids:
            db_session.query(model).filter(model.id.in_(ids)).delete(
                synchronize_session=False
            )
    db_session.commit()
