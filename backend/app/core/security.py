import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]

# A dummy hash used to equalise the cost of a login attempt for an unknown email with
# one for a known email. Without it, "no such user" returns in microseconds while a real
# user costs a full bcrypt verification, which leaks account existence via response time.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalisation", bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify a password, taking constant-ish time whether or not the user exists.

    Callers should pass ``None`` (or an empty string) when no user was found, so that the
    dummy hash is exercised and the timing profile matches a genuine failure.
    """
    candidate = hashed_password or _DUMMY_HASH
    try:
        matched = bcrypt.checkpw(
            plain_password.encode("utf-8"), candidate.encode("utf-8")
        )
    except ValueError:
        # Malformed stored hash. Treat as a failed login, never as a success.
        return False
    # An absent user must always fail, even in the astronomically unlikely case that the
    # supplied password matches the dummy hash.
    return bool(matched and hashed_password)


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def _create_token(
    subject: str | Any,
    tenant_id: str,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "tenant_id": tenant_id,
        "role": role,
        # `typ` is what stops a refresh token being replayed as an access token and vice
        # versa. Previously both were minted by the same function with identical claims,
        # so the httpOnly refresh cookie was itself a seven-day access token.
        "typ": token_type,
        # `jti` gives every token a stable identity, which is the prerequisite for
        # revocation and refresh-token rotation.
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(
    subject: str | Any,
    tenant_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    return _create_token(
        subject,
        tenant_id,
        role,
        "access",
        expires_delta or timedelta(minutes=settings.access_token_ttl_minutes),
    )


def create_refresh_token(
    subject: str | Any,
    tenant_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    return _create_token(
        subject,
        tenant_id,
        role,
        "refresh",
        expires_delta or timedelta(days=settings.refresh_token_ttl_days),
    )


def verify_token(token: str, expected_type: TokenType | None = None) -> dict:
    """Decode and validate a token.

    Raises ``jose.JWTError`` for a bad signature or expiry, and ``ValueError`` when the
    token is well-formed but of the wrong kind. Callers that care about the distinction
    should catch both; callers that don't should treat either as a 401.
    """
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])

    if expected_type is not None:
        actual = payload.get("typ")
        if actual != expected_type:
            raise ValueError(
                f"expected a {expected_type} token, got {actual or 'untyped'}"
            )

    return payload
