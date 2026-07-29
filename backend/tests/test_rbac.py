from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.rbac import RoleChecker, check_tool_access
from app.core.security import create_access_token, create_refresh_token

app = FastAPI()


@app.get("/api/copilot/query")
def copilot_endpoint(user: dict = Depends(RoleChecker())):
    return {"status": "ok", "user": user}


@app.get("/api/admin/users")
def admin_endpoint(user: dict = Depends(RoleChecker())):
    return {"status": "ok", "user": user}


client = TestClient(app)


def test_viewer_access():
    token = create_access_token("user1", "tenant1", "viewer")
    headers = {"Authorization": f"Bearer {token}"}

    # Allowed
    resp = client.get("/api/copilot/query", headers=headers)
    assert resp.status_code == 200

    # Denied
    resp = client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 403

    # Tool access
    assert check_tool_access("viewer", "get_metric_trend") is True
    assert check_tool_access("viewer", "compare_segments") is False


def test_analyst_access():
    token = create_access_token("user2", "tenant1", "analyst")
    headers = {"Authorization": f"Bearer {token}"}

    # Allowed
    resp = client.get("/api/copilot/query", headers=headers)
    assert resp.status_code == 200

    # Denied
    resp = client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 403

    # Tool access
    assert check_tool_access("analyst", "compare_segments") is True
    assert check_tool_access("analyst", "list_active_alerts") is False


def test_admin_access():
    token = create_access_token("user3", "tenant1", "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Allowed
    resp = client.get("/api/copilot/query", headers=headers)
    assert resp.status_code == 200

    resp = client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 200

    # Tool access
    assert check_tool_access("admin", "list_active_alerts") is True


def test_invalid_token():
    headers = {"Authorization": "Bearer invalid"}
    resp = client.get("/api/copilot/query", headers=headers)
    assert resp.status_code == 401


def test_refresh_token_rejected_as_bearer_token():
    """A stolen refresh_token cookie must not work as an API bearer token.

    Regression test: get_current_user used to call verify_token() without
    expected_type="access", so a refresh token — mintable with a 7-day lifetime and
    handed to the browser as an httpOnly cookie — could be replayed directly against
    every API endpoint, defeating the access/refresh split entirely.
    """
    token = create_refresh_token("user1", "tenant1", "viewer")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/copilot/query", headers=headers)
    assert resp.status_code == 401
