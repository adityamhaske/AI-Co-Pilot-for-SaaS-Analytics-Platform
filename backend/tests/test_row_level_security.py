"""Row-level security, verified by trying to defeat it.

A migration that runs is not evidence that a policy works. These connect as a role that
does *not* own the tables — the only condition under which PostgreSQL applies RLS — and
attempt the cross-tenant read the policy is supposed to stop.

Skipped entirely on SQLite, which has no row-level security. That skip is itself the
reason the application-side filter in `app/metrics/compiler.py` remains the primary
control: the fast local path does not have this layer.
"""

import pytest
from sqlalchemy import text

from app.db.models import Customer, Subscription, Tenant
from app.db.session import Base
from tests.conftest import SQLALCHEMY_DATABASE_URL, TestingSessionLocal, engine

pytestmark = pytest.mark.skipif(
    not SQLALCHEMY_DATABASE_URL.startswith("postgresql"),
    reason="row-level security is a PostgreSQL feature; run with DATABASE_URL=postgresql+psycopg://…",
)

TENANT_A = "rls_tenant_a"
TENANT_B = "rls_tenant_b"
UNPRIVILEGED_ROLE = "rls_probe"


@pytest.fixture
def rls_world():
    """Two tenants with one customer each, plus policies and a non-owning role."""
    from alembic.migration import MigrationContext

    session = TestingSessionLocal()
    Base.metadata.create_all(bind=engine)

    # Apply the policies directly rather than through alembic, so this test does not
    # depend on where the suite's migration state happens to be.
    with engine.begin() as connection:
        MigrationContext.configure(connection)
        for table in ("customers", "subscriptions"):
            connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            connection.execute(
                text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            )
            connection.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {table} "
                    "USING (tenant_id = current_setting('app.current_tenant', true))"
                )
            )
        connection.execute(
            text(
                f"DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{UNPRIVILEGED_ROLE}') "
                f"THEN CREATE ROLE {UNPRIVILEGED_ROLE}; END IF; END $$;"
            )
        )
        # USAGE on the schema as well as SELECT on the tables: without it the role cannot
        # resolve the relation at all, which fails as "does not exist" rather than as a
        # permission error and looks nothing like an RLS result.
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {UNPRIVILEGED_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT ON customers, subscriptions TO {UNPRIVILEGED_ROLE}")
        )

    for tid in (TENANT_A, TENANT_B):
        if not session.query(Tenant).filter(Tenant.id == tid).first():
            session.add(Tenant(id=tid, name=tid))
    session.flush()
    session.add_all(
        [
            Customer(id="rls_cust_a", tenant_id=TENANT_A, name="Alpha", segment="smb"),
            Customer(id="rls_cust_b", tenant_id=TENANT_B, name="Bravo", segment="smb"),
        ]
    )
    session.commit()

    yield session

    session.rollback()
    session.query(Subscription).filter(
        Subscription.tenant_id.in_([TENANT_A, TENANT_B])
    ).delete(synchronize_session=False)
    session.query(Customer).filter(
        Customer.tenant_id.in_([TENANT_A, TENANT_B])
    ).delete(synchronize_session=False)
    session.query(Tenant).filter(Tenant.id.in_([TENANT_A, TENANT_B])).delete(
        synchronize_session=False
    )
    session.commit()
    session.close()


def names_visible_as(role_applied: bool, tenant: str | None) -> list[str]:
    """Read customer names, optionally as the unprivileged role and/or a declared tenant."""
    with engine.begin() as connection:
        if role_applied:
            # SET ROLE makes the session a non-owner, which is what activates RLS.
            connection.execute(text(f"SET LOCAL ROLE {UNPRIVILEGED_ROLE}"))
        if tenant is not None:
            # set_config(..., true) is the parameterisable equivalent of SET LOCAL.
            connection.execute(
                text("SELECT set_config('app.current_tenant', :t, true)"), {"t": tenant}
            )
        rows = connection.execute(
            text("SELECT name FROM customers WHERE id LIKE 'rls_cust_%' ORDER BY name")
        ).all()
    return [r[0] for r in rows]


def test_the_owner_bypasses_rls(rls_world):
    """Documented and deliberate: it is what keeps migrations and seeding working."""
    assert names_visible_as(role_applied=False, tenant=None) == ["Alpha", "Bravo"]


def test_an_undeclared_connection_sees_nothing(rls_world):
    """Fail-closed. Forgetting to declare the tenant must not mean "see everything"."""
    assert names_visible_as(role_applied=True, tenant=None) == []


def test_a_declared_tenant_sees_only_its_own_rows(rls_world):
    assert names_visible_as(role_applied=True, tenant=TENANT_A) == ["Alpha"]
    assert names_visible_as(role_applied=True, tenant=TENANT_B) == ["Bravo"]


def test_a_tenant_cannot_reach_another_by_asking_directly(rls_world):
    """The whole point: raw SQL naming the other tenant still returns nothing.

    This is the case the application-side filter cannot defend against on its own — a
    query written outside `metrics/compiler.py`, or a bug inside it.
    """
    with engine.begin() as connection:
        connection.execute(text(f"SET LOCAL ROLE {UNPRIVILEGED_ROLE}"))
        connection.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT_A}
        )
        rows = connection.execute(
            text("SELECT name FROM customers WHERE tenant_id = :other"),
            {"other": TENANT_B},
        ).all()
    assert rows == []


def test_the_setting_does_not_leak_between_transactions(rls_world):
    """SET LOCAL is transaction-scoped, so a pooled connection cannot carry it forward."""
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :t, true)"), {"t": TENANT_A}
        )

    with engine.begin() as connection:
        leaked = connection.execute(
            text("SELECT current_setting('app.current_tenant', true)")
        ).scalar()
    assert not leaked


def test_scope_session_to_tenant_sets_the_setting(rls_world, monkeypatch):
    from app.core.config import settings
    from app.db.tenancy import current_tenant, scope_session_to_tenant

    monkeypatch.setattr(settings, "enable_row_level_security", True)

    session = TestingSessionLocal()
    try:
        scope_session_to_tenant(session, TENANT_A)
        assert current_tenant(session) == TENANT_A
    finally:
        session.rollback()
        session.close()


def test_scope_session_is_a_no_op_when_disabled(rls_world, monkeypatch):
    """Off by default, so local development and the SQLite path are unaffected."""
    from app.core.config import settings
    from app.db.tenancy import current_tenant, scope_session_to_tenant

    monkeypatch.setattr(settings, "enable_row_level_security", False)

    session = TestingSessionLocal()
    try:
        scope_session_to_tenant(session, TENANT_A)
        assert current_tenant(session) is None
    finally:
        session.rollback()
        session.close()
