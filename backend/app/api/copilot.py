import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.conversations import service as conversations
from app.core import budget
from app.core.limiter import limiter
from app.core.rbac import RoleChecker
from app.api.deps import tenant_scoped_db
from app.db.session import SessionLocal
from app.guard.injection_guard import check_prompt_injection
from app.streaming.sse import stream_orchestrator

router = APIRouter()
logger = structlog.get_logger()


class QueryRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    #: Continue an existing conversation. Omit to start a new one.
    conversation_id: str | None = None


@router.post("/query")
@limiter.limit("10/minute")
async def copilot_query(
    request: Request,
    query_request: QueryRequest,
    current_user: dict = Depends(RoleChecker()),
    db: Session = Depends(tenant_scoped_db),
):
    user_id = current_user["user_id"]
    tenant_id = current_user["tenant_id"]
    role = current_user["role"]

    if not check_prompt_injection(query_request.message, user_id, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt injection detected."
        )

    # Cost is metered per user, because a request limit does not bound spend: one request
    # can drive several tool-calling steps over a large context.
    allowed, spent = budget.within_budget(db, user_id)
    if not allowed:
        logger.warning("budget_exceeded", user_id=user_id, spent_usd=spent)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily usage limit reached. Try again tomorrow.",
        )

    if query_request.conversation_id:
        conversation = conversations.get(
            db, tenant_id, user_id, query_request.conversation_id
        )
        if not conversation:
            # 404 rather than 403: an id belonging to another user must be
            # indistinguishable from one that does not exist.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
    else:
        conversation = conversations.create(
            db, tenant_id, user_id, conversations.derive_title(query_request.message)
        )

    history = conversations.history_for_model(db, conversation)
    conversations.add_message(db, conversation, "user", query_request.message)

    conversation_id = conversation.id

    def persist(answer: str, tools: list[dict], usage: dict) -> None:
        # The request-scoped session may already be closing by the time the stream ends,
        # so this uses its own short-lived session.
        own = SessionLocal()
        try:
            stored = conversations.get(own, tenant_id, user_id, conversation_id)
            if stored is not None:
                conversations.add_message(own, stored, "assistant", answer, tools)
            budget.record(
                own,
                tenant_id,
                user_id,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                conversation_id,
            )
        finally:
            own.close()

    return StreamingResponse(
        stream_orchestrator(
            db,
            tenant_id,
            role,
            query_request.message,
            history=history,
            on_complete=persist,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells nginx not to buffer, which would otherwise defeat streaming entirely.
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conversation_id,
        },
    )
