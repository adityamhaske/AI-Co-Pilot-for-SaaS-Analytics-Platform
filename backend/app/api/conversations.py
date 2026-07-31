"""Conversation history endpoints.

Every handler resolves the conversation through `service.get`, which filters on tenant
*and* user. A conversation belonging to someone else returns 404, not 403: a 403 would
confirm the id exists.
"""

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import tenant_scoped_db
from app.conversations import service
from app.core.rbac import get_current_user

router = APIRouter()


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    message_count: int = 0


class ToolInvocation(BaseModel):
    name: str
    input: dict | None = None
    data: object | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    tools: list[ToolInvocation] = Field(default_factory=list)
    created_at: datetime.datetime | None = None


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = Field(default_factory=list)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(tenant_scoped_db),
):
    return service.list_for_user(db, current_user["tenant_id"], current_user["user_id"])


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(tenant_scoped_db),
):
    conversation = service.get(
        db, current_user["tenant_id"], current_user["user_id"], conversation_id
    )
    if not conversation:
        raise _NOT_FOUND

    stored = service.messages(db, conversation.id, conversation.tenant_id)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(stored),
        messages=[service.serialise_message(m) for m in stored],
    )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    payload: RenameRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(tenant_scoped_db),
):
    conversation = service.rename(
        db,
        current_user["tenant_id"],
        current_user["user_id"],
        conversation_id,
        payload.title,
    )
    if not conversation:
        raise _NOT_FOUND
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(tenant_scoped_db),
):
    if not service.delete(
        db, current_user["tenant_id"], current_user["user_id"], conversation_id
    ):
        raise _NOT_FOUND
