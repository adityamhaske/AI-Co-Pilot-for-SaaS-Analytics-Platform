from fastapi import Depends, HTTPException, Request, status

from app.core.security import verify_token

# RBAC matrix.
#
# This gates the *tool* (the query shape). Which *metrics* a role may read through those
# tools is a second, independent gate: `minimum_role` on each definition in
# app/metrics/definitions. A role needs to pass both, so widening one never silently
# widens the other.
#
# `get_metric_value` replaced the single-purpose `get_churn_rate`: it reads any metric
# that declares snapshot support, churn included.
ROLE_PERMISSIONS = {
    "viewer": {
        "endpoints": ["/api/copilot/query"],
        "tools": ["get_metric_trend", "get_metric_value"],
    },
    "analyst": {
        "endpoints": ["/api/copilot/query"],
        "tools": [
            "get_metric_trend",
            "get_metric_value",
            "compare_segments",
            "get_top_customers",
        ],
    },
    "admin": {
        "endpoints": ["/api/copilot/query", "/api/admin/users"],
        "tools": [
            "get_metric_trend",
            "get_metric_value",
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
        # `from None` deliberately drops the cause: the PyJWT error text distinguishes an
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
    """Dependency that admits a request only if the caller's role covers its path.

    Takes no arguments. It previously accepted an `allowed_endpoints` list that was
    stored and never read — the decision has always come from ROLE_PERMISSIONS — so a
    call site could pass a convincing-looking allow-list and silently have no effect.
    """

    def __call__(
        self, request: Request, current_user: dict = Depends(get_current_user)
    ):
        role = current_user.get("role")
        if role not in ROLE_PERMISSIONS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role"
            )

        # Exact match, or a path segment beneath an allowed prefix. `startswith` alone
        # let `/api/copilot/queryX` satisfy a grant of `/api/copilot/query`, so any
        # future sibling route would inherit permissions it was never granted.
        path = request.url.path.rstrip("/")
        allowed = any(
            path == endpoint or path.startswith(endpoint + "/")
            for endpoint in ROLE_PERMISSIONS[role]["endpoints"]
        )

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
