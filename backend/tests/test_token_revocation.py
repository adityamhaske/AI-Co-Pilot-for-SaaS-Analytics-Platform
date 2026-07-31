"""Refresh-token rotation, revocation and reuse detection.

A signed JWT cannot be withdrawn on its own. These assert that the token store actually
closes that gap: signing out kills the token, using one rotates it, and replaying a
rotated one burns the whole family.
"""

import pytest

from app.core import tokens as token_store
from app.core.budget import estimate_cost, record, spend_today, within_budget
from app.core.security import create_refresh_token, get_password_hash, verify_token
from app.db.models import RefreshToken, Tenant, User

TENANT = "tenant_tok"
USER = "tok_user"


@pytest.fixture
def token_user(db_session):
    if not db_session.query(Tenant).filter(Tenant.id == TENANT).first():
        db_session.add(Tenant(id=TENANT, name=TENANT))
    if not db_session.query(User).filter(User.id == USER).first():
        db_session.add(
            User(
                id=USER,
                tenant_id=TENANT,
                email="tok@test.com",
                hashed_password=get_password_hash("password123"),
                role="viewer",
            )
        )
    db_session.commit()
    yield db_session

    from app.db.models import UsageRecord

    db_session.query(RefreshToken).filter(RefreshToken.user_id == USER).delete(
        synchronize_session=False
    )
    db_session.query(UsageRecord).filter(UsageRecord.user_id == USER).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.id == USER).delete(synchronize_session=False)
    db_session.query(Tenant).filter(Tenant.id == TENANT).delete(
        synchronize_session=False
    )
    db_session.commit()


def issue(db):
    token = create_refresh_token(USER, TENANT, "viewer")
    token_store.store(db, token, USER, TENANT)
    return token


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_stored_token_is_live(token_user):
    token = issue(token_user)
    assert token_store.is_live(token_user, token.jti)


def test_rotation_consumes_the_old_token(token_user):
    old = issue(token_user)
    new = create_refresh_token(USER, TENANT, "viewer")

    assert token_store.rotate(token_user, old.jti, new, USER) is True
    assert not token_store.is_live(token_user, old.jti)
    assert token_store.is_live(token_user, new.jti)


def test_rotation_records_the_replacement(token_user):
    old = issue(token_user)
    new = create_refresh_token(USER, TENANT, "viewer")
    token_store.rotate(token_user, old.jti, new, USER)

    row = token_user.query(RefreshToken).filter(RefreshToken.jti == old.jti).first()
    assert row.replaced_by == new.jti


def test_unknown_jti_is_refused(token_user):
    """A correctly-signed token we never issued must not be honoured."""
    replacement = create_refresh_token(USER, TENANT, "viewer")
    assert token_store.rotate(token_user, "never_issued", replacement, USER) is False


def test_subject_mismatch_is_refused(token_user):
    token = issue(token_user)
    replacement = create_refresh_token("someone_else", TENANT, "viewer")
    assert (
        token_store.rotate(token_user, token.jti, replacement, "someone_else") is False
    )


# ---------------------------------------------------------------------------
# Reuse detection
# ---------------------------------------------------------------------------


def test_replaying_a_rotated_token_revokes_the_whole_family(token_user):
    """Two parties holding one credential means it leaked. Burn all of them."""
    first = issue(token_user)
    second = create_refresh_token(USER, TENANT, "viewer")
    token_store.rotate(token_user, first.jti, second, USER)
    assert token_store.is_live(token_user, second.jti)

    # The attacker replays the token they captured.
    third = create_refresh_token(USER, TENANT, "viewer")
    assert token_store.rotate(token_user, first.jti, third, USER) is False

    # The legitimate session is now dead too, forcing a re-login.
    assert not token_store.is_live(token_user, second.jti)


def test_logout_revokes_every_token(token_user):
    a, b = issue(token_user), issue(token_user)
    assert token_store.revoke_all_for_user(token_user, USER, reason="logout") == 2
    assert not token_store.is_live(token_user, a.jti)
    assert not token_store.is_live(token_user, b.jti)


# ---------------------------------------------------------------------------
# End to end through the API
# ---------------------------------------------------------------------------


def test_logout_makes_the_refresh_cookie_useless(client, test_user):
    login = client.post(
        "/api/auth/login", json={"email": "test@test.com", "password": "password123"}
    )
    cookie = login.cookies.get("refresh_token")
    assert cookie

    assert (
        client.post("/api/auth/logout", cookies={"refresh_token": cookie}).status_code
        == 200
    )

    replay = client.post("/api/auth/refresh", cookies={"refresh_token": cookie})
    assert replay.status_code == 401


def test_refresh_rotates_the_cookie(client, test_user):
    login = client.post(
        "/api/auth/login", json={"email": "test@test.com", "password": "password123"}
    )
    first = login.cookies.get("refresh_token")

    refreshed = client.post("/api/auth/refresh", cookies={"refresh_token": first})
    assert refreshed.status_code == 200
    second = refreshed.cookies.get("refresh_token")
    assert second and second != first

    # The old cookie is spent.
    assert (
        client.post("/api/auth/refresh", cookies={"refresh_token": first}).status_code
        == 401
    )


def test_refresh_token_carries_the_right_type(client, test_user):
    login = client.post(
        "/api/auth/login", json={"email": "test@test.com", "password": "password123"}
    )
    payload = verify_token(login.cookies.get("refresh_token"), expected_type="refresh")
    assert payload["typ"] == "refresh"
    assert payload["jti"]


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("anthropic", 18.0), ("openai", 10.0), ("gemini", 11.25)],
)
def test_cost_estimate_prices_each_provider_separately(provider, expected):
    """1M input + 1M output, priced from app.providers.PRICING.

    The provider is passed explicitly rather than read from settings: this assertion
    used to depend on the ambient LLM_PROVIDER, so a developer with `gemini` in their
    .env saw it fail on rates that were perfectly correct.
    """
    assert estimate_cost(1_000_000, 1_000_000, provider) == pytest.approx(expected)
    assert estimate_cost(0, 0, provider) == 0.0


def test_cost_estimate_falls_back_for_an_unknown_provider():
    # Unknown names price at the most expensive published rate rather than free, so a
    # misconfiguration cannot quietly disable the budget ceiling.
    assert estimate_cost(1_000_000, 1_000_000, "no-such-provider") == pytest.approx(18.0)


def test_spend_accumulates(token_user):
    assert spend_today(token_user, USER) == 0.0
    record(token_user, TENANT, USER, 100_000, 10_000)
    first = spend_today(token_user, USER)
    assert first > 0
    record(token_user, TENANT, USER, 100_000, 10_000)
    assert spend_today(token_user, USER) == pytest.approx(first * 2)


def _output_tokens_worth(dollars: float) -> int:
    """Output tokens that cost at least `dollars` under the *configured* provider.

    Deriving the rate keeps these tests about the budget ceiling rather than about any
    one vendor's price list.
    """
    from app.core.config import settings
    from app.providers import pricing_for

    _, output_rate = pricing_for(settings.llm_provider)
    return int((dollars / output_rate) * 1_000_000) + 1


def test_budget_blocks_once_the_ceiling_is_passed(token_user):
    from app.core.config import settings

    allowed, _ = within_budget(token_user, USER)
    assert allowed

    # Spend well past the daily limit.
    tokens_needed = _output_tokens_worth(settings.daily_cost_limit_usd)
    record(token_user, TENANT, USER, 0, tokens_needed)

    allowed, spent = within_budget(token_user, USER)
    assert not allowed
    assert spent >= settings.daily_cost_limit_usd


def test_budget_is_per_user(token_user):
    from app.core.config import settings

    tokens_needed = _output_tokens_worth(settings.daily_cost_limit_usd)
    record(token_user, TENANT, USER, 0, tokens_needed)

    assert not within_budget(token_user, USER)[0]
    # A different user is unaffected.
    assert within_budget(token_user, "some_other_user")[0]
