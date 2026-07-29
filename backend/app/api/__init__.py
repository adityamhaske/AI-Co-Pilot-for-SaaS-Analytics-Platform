from fastapi import APIRouter

from app.api import auth, conversations, copilot

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(copilot.router, prefix="/copilot", tags=["copilot"])
api_router.include_router(
    conversations.router, prefix="/conversations", tags=["conversations"]
)
