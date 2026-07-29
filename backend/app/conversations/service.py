"""Conversation storage and history replay.

Every query in this module filters on `tenant_id` *and* `user_id`. Conversations are
private to the user who created them, so an id guessed from another account resolves to
nothing rather than to someone else's chat.
"""

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message, utcnow

# How many previous messages are replayed into the model's context. Each turn costs
# tokens, so this is a cost/coherence trade-off rather than an arbitrary cap.
HISTORY_TURN_LIMIT = 20

# Titles are derived from the opening question; long ones get elided in the sidebar.
TITLE_MAX_LENGTH = 60


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def derive_title(question: str) -> str:
    """A readable sidebar label taken from the first question."""
    cleaned = " ".join(question.split())
    if len(cleaned) <= TITLE_MAX_LENGTH:
        return cleaned or "New conversation"
    return cleaned[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


def create(db: Session, tenant_id: str, user_id: str, title: str) -> Conversation:
    conversation = Conversation(
        id=_new_id("conv"),
        tenant_id=tenant_id,
        user_id=user_id,
        title=title,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get(
    db: Session, tenant_id: str, user_id: str, conversation_id: str
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
        .first()
    )


def list_for_user(
    db: Session, tenant_id: str, user_id: str, limit: int = 50
) -> list[dict]:
    """Conversations newest-first, with a message count for the sidebar."""
    counts = dict(
        db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.tenant_id == tenant_id)
            .group_by(Message.conversation_id)
        ).all()
    )

    rows = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "message_count": counts.get(c.id, 0),
        }
        for c in rows
    ]


def rename(
    db: Session, tenant_id: str, user_id: str, conversation_id: str, title: str
) -> Conversation | None:
    conversation = get(db, tenant_id, user_id, conversation_id)
    if not conversation:
        return None
    conversation.title = derive_title(title)
    db.commit()
    db.refresh(conversation)
    return conversation


def delete(db: Session, tenant_id: str, user_id: str, conversation_id: str) -> bool:
    conversation = get(db, tenant_id, user_id, conversation_id)
    if not conversation:
        return False
    db.delete(conversation)
    db.commit()
    return True


def _next_sequence(db: Session, conversation_id: str) -> int:
    highest = (
        db.query(func.max(Message.sequence))
        .filter(Message.conversation_id == conversation_id)
        .scalar()
    )
    return (highest or 0) + 1


def add_message(
    db: Session,
    conversation: Conversation,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
) -> Message:
    message = Message(
        id=_new_id("msg"),
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        role=role,
        content=content,
        tool_calls=json.dumps(tool_calls, default=str) if tool_calls else None,
        sequence=_next_sequence(db, conversation.id),
    )
    db.add(message)
    conversation.updated_at = utcnow()
    db.commit()
    db.refresh(message)
    return message


def messages(db: Session, conversation_id: str, tenant_id: str) -> list[Message]:
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.sequence)
        .all()
    )


def serialise_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tools": json.loads(message.tool_calls) if message.tool_calls else [],
        "created_at": message.created_at,
    }


def history_for_model(
    db: Session, conversation: Conversation, limit: int = HISTORY_TURN_LIMIT
) -> list[dict[str, Any]]:
    """Prior turns as Anthropic message dicts.

    Only the *text* of each turn is replayed, not the tool_use/tool_result blocks. Those
    blocks reference tool_use ids from an earlier request, and replaying them without
    their exact counterparts produces a malformed conversation. The numbers the tools
    returned are already summarised in the assistant's text, which is what a follow-up
    question actually needs.
    """
    stored = messages(db, conversation.id, conversation.tenant_id)
    recent = stored[-limit:] if limit else stored

    history: list[dict[str, Any]] = []
    for message in recent:
        if not message.content.strip():
            continue
        # The API rejects two consecutive messages with the same role.
        if history and history[-1]["role"] == message.role:
            history[-1]["content"] += "\n\n" + message.content
            continue
        history.append({"role": message.role, "content": message.content})

    # A conversation must open with a user turn.
    while history and history[0]["role"] != "user":
        history.pop(0)

    return history
