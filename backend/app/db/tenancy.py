"""Row-level security: the second tenant-isolation layer.

Isolation is enforced in the application by `app/metrics/compiler.py`, which is the only
path that builds a query and always applies the tenant predicate. That is one layer. A
bug in the compiler, or a future query written outside it, has nothing behind it.

This adds the second layer in the database itself. Every tenant-scoped table carries a
policy of the form::

    tenant_id = current_setting('app.current_tenant', true)

so a connection that has not declared its tenant sees no rows at all — fail-closed — and
one that has declared it cannot see another tenant's rows whatever SQL it runs.

**RLS only binds a role that does not own the tables.** PostgreSQL exempts the owner
unless `FORCE ROW LEVEL SECURITY` is set, and forcing it would break migrations, seeding,
and the cross-tenant assertions in the test suite, all of which legitimately span
tenants. So the deployment contract is: migrate and seed as the owner, run the API as a
separate non-owning role. `docs/security/design.md` spells this out, and
`enable_row_level_security` makes the application-side half explicit rather than implied.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

logger = structlog.get_logger()

# Tables whose every row belongs to exactly one tenant. `users` and `tenants` are
# deliberately excluded: authentication has to find a user *before* it knows which tenant
# to scope to, so a policy on them would deadlock login against itself.
TENANT_SCOPED_TABLES = (
    "customers",
    "subscriptions",
    "invoices",
    "usage_events",
    "conversations",
    "messages",
    "usage_records",
)

SETTING = "app.current_tenant"


def scope_session_to_tenant(db: Session, tenant_id: str) -> None:
    """Declare the tenant for this transaction.

    Uses ``SET LOCAL``, so the value is scoped to the surrounding transaction and cannot
    leak to the next request that borrows the same pooled connection.

    A no-op on SQLite, which has no row-level security. That is why the application-side
    filter remains the primary control rather than a belt to this brace: local
    development and the fast test path do not have this layer at all.
    """
    if not settings.enable_row_level_security:
        return
    if db.bind is None or not db.bind.dialect.name.startswith("postgres"):
        return

    # `set_config(name, value, is_local)` rather than `SET LOCAL`: the latter is a utility
    # statement and cannot take a bind parameter, so it would force the tenant id to be
    # spliced into SQL — an injection point in the one mechanism meant to contain a
    # compromise. The third argument `true` makes it transaction-scoped, exactly like
    # SET LOCAL, so the value cannot outlive the request on a pooled connection.
    db.execute(
        text("SELECT set_config(:setting, :tenant, true)"),
        {"setting": SETTING, "tenant": tenant_id},
    )


def current_tenant(db: Session) -> str | None:
    """Whatever tenant this transaction has declared, for assertions and diagnostics."""
    if db.bind is None or not db.bind.dialect.name.startswith("postgres"):
        return None
    result = db.execute(text(f"SELECT current_setting('{SETTING}', true)")).scalar()
    return result or None
