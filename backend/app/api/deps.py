"""Shared request dependencies."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.rbac import get_current_user
from app.db.session import get_db
from app.db.tenancy import scope_session_to_tenant


def tenant_scoped_db(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> Iterator[Session]:
    """A session that has declared its tenant to the database.

    Prefer this over `get_db` in any handler that already knows the caller. When
    row-level security is enabled, the declaration is what makes the database enforce
    isolation; without it a policy-protected table returns nothing at all, which is the
    correct fail-closed behaviour but a confusing way to discover a missing dependency.

    A no-op on SQLite and when `enable_row_level_security` is off, so the application-side
    filter in `app/metrics/compiler.py` stays the primary control either way.
    """
    scope_session_to_tenant(db, current_user["tenant_id"])
    yield db
