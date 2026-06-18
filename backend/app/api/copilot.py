from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.rbac import RoleChecker
from app.guard.injection_guard import check_prompt_injection
from app.streaming.sse import stream_orchestrator
from app.core.limiter import limiter

router = APIRouter()

class QueryRequest(BaseModel):
    message: str

@router.post("/query")
@limiter.limit("10/minute")
async def copilot_query(
    request: Request,
    query_request: QueryRequest,
    current_user: dict = Depends(RoleChecker(allowed_endpoints=["/api/copilot/query"])),
    db: Session = Depends(get_db)
):
    user_id = current_user["user_id"]
    tenant_id = current_user["tenant_id"]
    role = current_user["role"]
    
    # Check injection guard
    is_safe = check_prompt_injection(query_request.message, user_id, tenant_id)
    if not is_safe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt injection detected."
        )
    
    # Return StreamingResponse
    return StreamingResponse(
        stream_orchestrator(db, tenant_id, role, query_request.message),
        media_type="text/event-stream"
    )
