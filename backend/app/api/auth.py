import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiter import limiter
from app.core.rbac import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_token,
)
from app.db.models import User
from app.db.session import get_db

router = APIRouter()
logger = structlog.get_logger()

REFRESH_COOKIE = "refresh_token"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    role: str
    tenant_id: str


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
    )


def _issue(user: User, response: Response) -> TokenResponse:
    access = create_access_token(
        subject=user.id, tenant_id=user.tenant_id, role=user.role
    )
    refresh = create_refresh_token(
        subject=user.id, tenant_id=user.tenant_id, role=user.role
    )
    _set_refresh_cookie(response, refresh)
    return TokenResponse(
        access_token=access,
        token_type="bearer",  # noqa: S106 — OAuth scheme name, not a credential
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    login_data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == login_data.email).first()

    # Always run the password check, even when no user matched: verify_password falls
    # back to a dummy hash so an unknown email costs the same as a wrong password. This
    # closes the timing side channel that let an attacker enumerate valid accounts.
    if not verify_password(login_data.password, user.hashed_password if user else None):
        logger.warning(
            "login_failed", email=login_data.email, user_found=user is not None
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    logger.info("login_succeeded", user_id=user.id, tenant_id=user.tenant_id)
    return _issue(user, response)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing"
        )

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
    )

    try:
        # expected_type rejects an access token presented as a refresh token.
        payload = verify_token(token, expected_type="refresh")
    except Exception:
        raise invalid from None

    user_id = payload.get("sub")
    if not user_id:
        raise invalid from None

    # Re-read the user on every refresh. Trusting the claims baked into the token meant a
    # demoted or deleted user kept minting fresh tokens carrying their old role for the
    # full refresh-token lifetime.
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning("refresh_for_unknown_user", user_id=user_id)
        raise invalid from None

    if user.role != payload.get("role") or user.tenant_id != payload.get("tenant_id"):
        # Authorisation changed since this token was minted. Force a re-login rather than
        # silently carrying the stale role forward.
        logger.warning(
            "refresh_claims_stale",
            user_id=user_id,
            token_role=payload.get("role"),
            current_role=user.role,
        )
        raise invalid from None

    # Rotate: every refresh issues a fresh refresh cookie alongside the access token.
    return _issue(user, response)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=REFRESH_COOKIE)
    return {"status": "logged_out"}


@router.get("/me", response_model=CurrentUserResponse)
def me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # get_current_user only decodes the token's claims. Re-reading the row gives the
    # UI real identity (email) rather than one more thing baked into the JWT payload.
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return CurrentUserResponse(
        id=user.id, email=user.email, role=user.role, tenant_id=user.tenant_id
    )
