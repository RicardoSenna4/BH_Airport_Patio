from fastapi.testclient import TestClient

from app.main import app


def login(client: TestClient, email: str = "fiscal@aeroops.local") -> dict:
    response = client.post("/auth/login", data={"username": email, "password": "Aero@123"})
    assert response.status_code == 200
    return response.json()


def test_session_refresh_rotation_and_logout_revocation():
    with TestClient(app) as client:
        tokens = login(client)
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200

        rotated = client.post("/auth/refresh", json={"refresh_token": refresh})
        assert rotated.status_code == 200
        assert client.post("/auth/refresh", json={"refresh_token": refresh}).status_code == 401
        new_access = rotated.json()["access_token"]
        assert client.post("/auth/logout", headers={"Authorization": f"Bearer {new_access}"}).status_code == 204
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"}).status_code == 401


def test_login_rate_limit_and_audit_events():
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post("/auth/login", data={"username": "unknown@example.com", "password": "wrong"}).status_code == 401
        limited = client.post("/auth/login", data={"username": "unknown@example.com", "password": "wrong"})
        assert limited.status_code == 429
        assert "Retry-After" in limited.headers

        admin = login(client, "administrador@aeroops.local")
        events = client.get("/audit/auth-events", headers={"Authorization": f"Bearer {admin['access_token']}"})
        assert events.status_code == 200
        assert {event["outcome"] for event in events.json()} >= {"FAILURE", "RATE_LIMITED", "SUCCESS"}


def test_password_policy_permissions_and_security_headers():
    with TestClient(app) as client:
        fiscal = login(client)
        assert client.get("/users", headers={"Authorization": f"Bearer {fiscal['access_token']}"}).status_code == 403

        admin = login(client, "administrador@aeroops.local")
        headers = {"Authorization": f"Bearer {admin['access_token']}", "X-Request-ID": "acceptance-123"}
        weak = client.post("/users", headers=headers, json={"name": "Teste", "email": "teste@example.com", "password": "fraca", "role": "FISCAL"})
        assert weak.status_code == 422
        strong = client.post("/users", headers=headers, json={"name": "Teste", "email": "teste@example.com", "password": "SenhaForte@2026", "role": "FISCAL"})
        assert strong.status_code == 201
        assert strong.headers["X-Request-ID"] == "acceptance-123"
        assert strong.headers["X-Content-Type-Options"] == "nosniff"
        assert strong.headers["X-Frame-Options"] == "DENY"


def test_cors_only_allows_configured_origin():
    with TestClient(app) as client:
        allowed = client.options("/health", headers={"Origin": "http://testserver", "Access-Control-Request-Method": "GET"})
        assert allowed.headers.get("access-control-allow-origin") == "http://testserver"
        blocked = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in blocked.headers
