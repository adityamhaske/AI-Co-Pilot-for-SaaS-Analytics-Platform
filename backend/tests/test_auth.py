from datetime import timedelta
from app.core.security import create_access_token
import time

def test_login_success(client, test_user):
    response = client.post("/api/auth/login", json={"email": "test@test.com", "password": "password123"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    # check if cookie is set
    assert "refresh_token" in response.cookies

def test_login_invalid_password(client, test_user):
    response = client.post("/api/auth/login", json={"email": "test@test.com", "password": "wrong"})
    assert response.status_code == 401

def test_login_invalid_email(client, test_user):
    response = client.post("/api/auth/login", json={"email": "wrong@test.com", "password": "password123"})
    assert response.status_code == 401

def test_refresh_success(client, test_user):
    # First login to get the cookie
    login_resp = client.post("/api/auth/login", json={"email": "test@test.com", "password": "password123"})
    cookie = login_resp.cookies.get("refresh_token")
    
    response = client.post("/api/auth/refresh", cookies={"refresh_token": cookie})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data

def test_refresh_missing_cookie(client):
    response = client.post("/api/auth/refresh")
    assert response.status_code == 401

def test_refresh_expired_token(client):
    expired_token = create_access_token("user_test", "tenant_test", "viewer", expires_delta=timedelta(seconds=-1))
    response = client.post("/api/auth/refresh", cookies={"refresh_token": expired_token})
    assert response.status_code == 401

def test_refresh_tampered_token(client):
    tampered_token = create_access_token("user_test", "tenant_test", "viewer") + "bad"
    response = client.post("/api/auth/refresh", cookies={"refresh_token": tampered_token})
    assert response.status_code == 401
