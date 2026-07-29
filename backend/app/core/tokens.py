"""Refresh-token lifecycle: persistence, rotation and revocation.

A signed JWT alone cannot be withdrawn. Before this, signing out, changing a password or
losing a cookie all left the refresh token working until it expired — seven days of
access nobody could stop. Every issued refresh token now has a row, and using one
rotates it.

Rotation also gives reuse detection. A refresh token is meant to be used exactly once;
if an already-rotated token is presented again, either it was stolen or it was cloned, so
every token for that user is revoked and they must sign in again.
"""

import structlog
from sqlalchemy.orm import Session

from app.core.security import IssuedToken
from app.db.models import RefreshToken, utcnow

logger = structlog.get_logger()


def _naive(value):
    """Strip tzinfo for comparison: SQLite returns naive datetimes."""
    return value.replace(tzinfo=None) if value and value.tzinfo else value


def store(
    db: Session, issued: IssuedToken, user_id: str, tenant_id: str
) -> RefreshToken:
    row = RefreshToken(
        jti=issued.jti,
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=_naive(issued.expires_at),
    )
    db.add(row)
    db.commit()
    return row


def revoke_all_for_user(db: Session, user_id: str, reason: str) -> int:
    """Revoke every live token for a user. Used on logout and on reuse detection."""
    now = _naive(utcnow())
    count = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    if count:
        logger.info(
            "refresh_tokens_revoked", user_id=user_id, count=count, reason=reason
        )
    return count


def rotate(
    db: Session, presented_jti: str, replacement: IssuedToken, user_id: str
) -> bool:
    """Consume the presented token and record its replacement.

    Returns False when the presented token is unknown, already revoked or expired — the
    caller must reject the request. Presenting an already-rotated token revokes the whole
    family, because that means two parties hold the same credential.
    """
    row = db.query(RefreshToken).filter(RefreshToken.jti == presented_jti).first()

    if row is None:
        # Signed correctly but never issued by us, or issued before this table existed.
        logger.warning("refresh_token_unknown", jti=presented_jti, user_id=user_id)
        return False

    if row.revoked_at is not None:
        logger.warning(
            "refresh_token_reuse_detected",
            jti=presented_jti,
            user_id=row.user_id,
            replaced_by=row.replaced_by,
        )
        revoke_all_for_user(db, row.user_id, reason="reuse_detected")
        return False

    if _naive(row.expires_at) is not None and _naive(row.expires_at) < _naive(utcnow()):
        logger.info("refresh_token_expired", jti=presented_jti, user_id=row.user_id)
        return False

    if row.user_id != user_id:
        # The token's claims disagree with the stored row.
        logger.warning(
            "refresh_token_subject_mismatch",
            jti=presented_jti,
            claimed=user_id,
            stored=row.user_id,
        )
        return False

    row.revoked_at = _naive(utcnow())
    row.replaced_by = replacement.jti
    db.add(
        RefreshToken(
            jti=replacement.jti,
            user_id=user_id,
            tenant_id=row.tenant_id,
            expires_at=_naive(replacement.expires_at),
        )
    )
    db.commit()
    return True


def is_live(db: Session, jti: str) -> bool:
    row = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    return bool(row and row.revoked_at is None)
