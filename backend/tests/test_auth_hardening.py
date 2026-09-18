import pyotp
from fastapi.testclient import TestClient

from app.main import app


def login(client: TestClient, email: str = "fiscal@aeroops.local", **extra: str):
    return client.post(
        "/auth/login",
        data={"username": email, "password": "Aero@123", **extra},
    )


def test_cookie_authentication_is_http_only_and_csrf_protected():
    with TestClient(app) as client:
        response = login(client)
        assert response.status_code == 200
        cookies = response.headers.get_list("set-cookie")
        assert any("aeroops_access=" in value and "HttpOnly" in value and "SameSite=strict" in value for value in cookies)
        assert any("aeroops_refresh=" in value and "HttpOnly" in value and "SameSite=strict" in value for value in cookies)
        assert client.get("/auth/me").status_code == 200

        assert client.post("/auth/logout").status_code == 403
        csrf = client.cookies.get("aeroops_csrf")
        assert csrf
        assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
        assert client.get("/auth/me").status_code == 401


def test_mfa_enrollment_and_login_challenge():
    with TestClient(app) as client:
        authenticated = login(client)
        access = authenticated.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        setup = client.post("/auth/mfa/setup", headers=headers)
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        code = pyotp.TOTP(secret).now()
        assert client.post("/auth/mfa/confirm", headers=headers, json={"code": code}).status_code == 204

    with TestClient(app) as fresh_client:
        assert login(fresh_client).status_code == 401
        assert login(fresh_client, mfa_code=pyotp.TOTP(secret).now()).status_code == 200


def test_session_inventory_and_password_change_revoke_sessions():
    with TestClient(app) as client:
        authenticated = login(client)
        access = authenticated.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}
        sessions = client.get("/auth/sessions", headers=headers)
        assert sessions.status_code == 200
        assert len(sessions.json()) == 1

        changed = client.post(
            "/auth/password",
            headers=headers,
            json={"current_password": "Aero@123", "new_password": "Uma senha longa e nova 2026!"},
        )
        assert changed.status_code == 204
        assert client.get("/auth/me", headers=headers).status_code == 401
        client.cookies.clear()
        assert login(client).status_code == 401
        assert client.post(
            "/auth/login",
            data={"username": "fiscal@aeroops.local", "password": "Uma senha longa e nova 2026!"},
        ).status_code == 200
