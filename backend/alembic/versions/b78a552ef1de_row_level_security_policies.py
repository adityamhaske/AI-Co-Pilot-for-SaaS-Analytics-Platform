"""Row-level security policies.

PostgreSQL only. RLS is the second tenant-isolation layer, behind the application-side
filter in ``app/metrics/compiler.py``: a connection that has not declared its tenant sees
no rows, and one that has cannot reach another tenant's rows whatever SQL it runs.

Deliberately *not* ``FORCE ROW LEVEL SECURITY``. PostgreSQL exempts a table's owner, and
that exemption is what keeps migrations, seeding and the suite's cross-tenant isolation
assertions working — all of which legitimately span tenants. The deployment contract is
therefore: migrate and seed as the owner, run the API as a separate non-owning role.
Running the API as the owner leaves this layer inert, which is why the application-side
filter remains the primary control.

Revision ID: b78a552ef1de
Revises: cbc11b89a97d
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b78a552ef1de"
down_revision: str | Sequence[str] | None = "cbc11b89a97d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `users` and `tenants` are excluded on purpose: authentication has to find a user before
# it knows which tenant to scope to, so a policy on them would deadlock login.
TENANT_SCOPED_TABLES = (
    "customers",
    "subscriptions",
    "invoices",
    "usage_events",
    "conversations",
    "messages",
    "usage_records",
)

POLICY = "tenant_isolation"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        # SQLite has no row-level security. Local development and the fast test path run
        # with the application-side filter alone.
        return

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # `current_setting(..., true)` returns NULL rather than raising when the setting
        # is absent, so an undeclared connection matches nothing instead of erroring.
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} "
            "USING (tenant_id = current_setting('app.current_tenant', true))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
