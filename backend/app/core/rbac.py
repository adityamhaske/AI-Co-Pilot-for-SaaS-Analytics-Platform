from fastapi import Depends, HTTPException, Request, status

from app.core.security import verify_token

# RBAC Matrix
ROLE_PERMISSIONS = {
    "viewer": {
        "endpoints": ["/api/copilot/query"],
        "tools": ["get_metric_trend", "get_churn_rate"],
    },
    "analyst": {
        "endpoints": ["/api/copilot/query"],
        "tools": [
            "get_metric_trend",
            "get_churn_rate",
            "compare_segments",
            "get_top_customers",
        ],
    },
    "admin": {
        "endpoints": ["/api/copilot/query", "/api/admin/users"],
        "tools": [
            "get_metric_trend",
            "get_churn_rate",
            "compare_segments",
            "get_top_customers",
            "list_active_alerts",
        ],
    },
}


def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header.split(" ")[1]
    try:
        # expected_type="access" rejects a refresh token presented as a bearer token.
        # Without this check, a stolen refresh_token cookie could be replayed directly
        # against every API endpoint, which is exactly what the access/refresh split in
        # core/security.py is supposed to prevent.
        payload = verify_token(token, expected_type="access")
    except Exception:
        # `from None` deliberately drops the cause: the jose error text distinguishes an
        # expired token from a bad signature from a wrong type, which is an oracle an
        # attacker can use. The caller gets one undifferentiated 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    role = payload.get("role")

    if not user_id or not tenant_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )

    return {"user_id": user_id, "tenant_id": tenant_id, "role": role}


class RoleChecker:
    def __init__(self, allowed_endpoints: list[str] | None = None):
        self.allowed_endpoints = allowed_endpoints or []

    def __call__(
        self, request: Request, current_user: dict = Depends(get_current_user)
    ):
        role = current_user.get("role")
        if role not in ROLE_PERMISSIONS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role"
            )

        # Check endpoint access
        # For this project, we check if the requested path starts with any allowed endpoint for the role
        path = request.url.path
        allowed = False
        for ep in ROLE_PERMISSIONS[role]["endpoints"]:
            if path.startswith(ep):
                allowed = True
                break

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden endpoint for role",
            )

        return current_user


def check_tool_access(role: str, tool_name: str) -> bool:
    if role not in ROLE_PERMISSIONS:
        return False
    return tool_name in ROLE_PERMISSIONS[role]["tools"]
