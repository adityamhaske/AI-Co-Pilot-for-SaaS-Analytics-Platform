"""Conversation persistence, multi-turn history, and per-user isolation."""

import json

import pytest

from app.conversations import service
from app.core.security import create_access_token, get_password_hash
from app.db.models import Tenant, User

TENANT = "tenant_conv"
OTHER_TENANT = "tenant_conv_other"


@pytest.fixture
def two_users(db_session):
    """Two users in different tenants, plus a second user inside the same tenant."""
    for tid in (TENANT, OTHER_TENANT):
        if not db_session.query(Tenant).filter(Tenant.id == tid).first():
            db_session.add(Tenant(id=tid, name=tid))

    people = [
        ("conv_alice", TENANT, "alice@conv.test", "analyst"),
        ("conv_bob", TENANT, "bob@conv.test", "viewer"),
        ("conv_mallory", OTHER_TENANT, "mallory@conv.test", "admin"),
    ]
    for uid, tid, email, role in people:
        if not db_session.query(User).filter(User.id == uid).first():
            db_session.add(
                User(
                    id=uid,
                    tenant_id=tid,
                    email=email,
                    hashed_password=get_password_hash("password123"),
                    role=role,
                )
            )
    db_session.commit()
    yield db_session

    from app.db.models import Conversation, Message

    db_session.query(Message).filter(
        Message.tenant_id.in_([TENANT, OTHER_TENANT])
    ).delete(synchronize_session=False)
    db_session.query(Conversation).filter(
        Conversation.tenant_id.in_([TENANT, OTHER_TENANT])
    ).delete(synchronize_session=False)
    db_session.query(User).filter(
        User.id.in_(["conv_alice", "conv_bob", "conv_mallory"])
    ).delete(synchronize_session=False)
    db_session.query(Tenant).filter(Tenant.id.in_([TENANT, OTHER_TENANT])).delete(
        synchronize_session=False
    )
    db_session.commit()


def auth(user_id: str, tenant_id: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, tenant_id, role)}"}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def test_messages_keep_their_order(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Ordering")
    for i in range(5):
        service.add_message(two_users, conv, "user", f"question {i}")

    stored = service.messages(two_users, conv.id, TENANT)
    assert [m.content for m in stored] == [f"question {i}" for i in range(5)]
    assert [m.sequence for m in stored] == [1, 2, 3, 4, 5]


def test_tool_calls_round_trip(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Tools")
    tools = [
        {
            "name": "get_metric_value",
            "input": {"metric": "mrr"},
            "data": {"value": 5600},
        }
    ]
    service.add_message(two_users, conv, "assistant", "Your MRR is 5600.", tools)

    stored = service.messages(two_users, conv.id, TENANT)[0]
    assert json.loads(stored.tool_calls) == tools
    assert service.serialise_message(stored)["tools"] == tools


def test_title_is_derived_and_elided():
    assert service.derive_title("What is my MRR?") == "What is my MRR?"
    long = "word " * 60
    assert len(service.derive_title(long)) <= service.TITLE_MAX_LENGTH
    assert service.derive_title(long).endswith("…")
    assert service.derive_title("   ") == "New conversation"


def test_deleting_a_conversation_removes_its_messages(two_users):
    from app.db.models import Message

    conv = service.create(two_users, TENANT, "conv_alice", "Doomed")
    service.add_message(two_users, conv, "user", "hello")
    conv_id = conv.id

    assert service.delete(two_users, TENANT, "conv_alice", conv_id) is True
    assert (
        two_users.query(Message).filter(Message.conversation_id == conv_id).count() == 0
    )


# ---------------------------------------------------------------------------
# History replay
# ---------------------------------------------------------------------------


def test_history_alternates_roles(two_users):
    """The API rejects two consecutive messages with the same role."""
    conv = service.create(two_users, TENANT, "conv_alice", "Alternating")
    service.add_message(two_users, conv, "user", "first")
    service.add_message(two_users, conv, "user", "second")
    service.add_message(two_users, conv, "assistant", "reply")

    history = service.history_for_model(two_users, conv)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]
    # The two user turns were merged rather than dropped.
    assert "first" in history[0]["content"] and "second" in history[0]["content"]


def test_history_starts_with_a_user_turn(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Leading assistant")
    service.add_message(two_users, conv, "assistant", "unprompted greeting")
    service.add_message(two_users, conv, "user", "actual question")

    history = service.history_for_model(two_users, conv)
    assert history[0]["role"] == "user"


def test_history_skips_empty_messages(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Empty")
    service.add_message(two_users, conv, "user", "real")
    service.add_message(two_users, conv, "assistant", "   ")

    history = service.history_for_model(two_users, conv)
    assert len(history) == 1


def test_history_is_truncated_to_the_limit(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Long")
    for i in range(30):
        service.add_message(
            two_users, conv, "user" if i % 2 == 0 else "assistant", f"m{i}"
        )

    history = service.history_for_model(two_users, conv, limit=6)
    assert len(history) <= 6
    # Truncation keeps the *most recent* turns.
    assert "m29" in history[-1]["content"]


# ---------------------------------------------------------------------------
# Isolation — the property that matters most
# ---------------------------------------------------------------------------


def test_a_user_cannot_read_another_users_conversation(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Alice private")
    # Same tenant, different user.
    assert service.get(two_users, TENANT, "conv_bob", conv.id) is None
    # Different tenant entirely.
    assert service.get(two_users, OTHER_TENANT, "conv_mallory", conv.id) is None


def test_listing_only_returns_your_own(two_users):
    service.create(two_users, TENANT, "conv_alice", "Alice one")
    service.create(two_users, TENANT, "conv_bob", "Bob one")

    alice = service.list_for_user(two_users, TENANT, "conv_alice")
    assert [c["title"] for c in alice] == ["Alice one"]


def test_delete_and_rename_refuse_other_users(two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Alice private")
    assert service.delete(two_users, TENANT, "conv_bob", conv.id) is False
    assert service.rename(two_users, TENANT, "conv_bob", conv.id, "hijacked") is None
    assert (
        service.get(two_users, TENANT, "conv_alice", conv.id).title == "Alice private"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def test_endpoints_require_authentication(client):
    assert client.get("/api/conversations").status_code == 401


def test_list_and_fetch_via_api(client, two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Via API")
    service.add_message(two_users, conv, "user", "hello")

    headers = auth("conv_alice", TENANT, "analyst")
    listing = client.get("/api/conversations", headers=headers)
    assert listing.status_code == 200
    assert any(c["id"] == conv.id for c in listing.json())

    detail = client.get(f"/api/conversations/{conv.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["messages"][0]["content"] == "hello"


def test_other_users_conversation_is_404_not_403(client, two_users):
    """403 would confirm the id exists. It must be indistinguishable from absent."""
    conv = service.create(two_users, TENANT, "conv_alice", "Alice private")
    resp = client.get(
        f"/api/conversations/{conv.id}", headers=auth("conv_bob", TENANT, "viewer")
    )
    assert resp.status_code == 404


def test_rename_and_delete_via_api(client, two_users):
    conv = service.create(two_users, TENANT, "conv_alice", "Before")
    headers = auth("conv_alice", TENANT, "analyst")

    renamed = client.patch(
        f"/api/conversations/{conv.id}", json={"title": "After"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "After"

    assert (
        client.delete(f"/api/conversations/{conv.id}", headers=headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/conversations/{conv.id}", headers=headers).status_code == 404
    )


def test_unknown_conversation_id_on_query_is_rejected(client, two_users):
    resp = client.post(
        "/api/copilot/query",
        headers=auth("conv_alice", TENANT, "analyst"),
        json={"message": "hi", "conversation_id": "conv_does_not_exist"},
    )
    assert resp.status_code == 404


def test_empty_message_is_rejected(client, two_users):
    resp = client.post(
        "/api/copilot/query",
        headers=auth("conv_alice", TENANT, "analyst"),
        json={"message": ""},
    )
    assert resp.status_code == 422
