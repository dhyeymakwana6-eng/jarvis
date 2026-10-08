from datetime import datetime, timedelta, timezone

import pytest

from app.models.auth_session import AuthSession
from app.services.auth_service import AuthService


@pytest.fixture
def locked(monkeypatch):
    """Auth on, with a clean failure count and token cache."""
    monkeypatch.setenv("JARVIS_PASSCODE", "open sesame")
    monkeypatch.setattr(AuthService, "_failures", [])
    monkeypatch.setattr(AuthService, "_cache", {})


def test_open_without_a_passcode(client):
    assert client.get("/auth/status").json() == {"required": False, "authenticated": True}
    assert client.get("/tasks").status_code == 200
    assert client.post("/auth/login", json={"passcode": "x"}).status_code == 400


def test_everything_but_auth_and_health_needs_a_session(client, locked):
    assert client.get("/").status_code == 200
    assert client.get("/auth/status").json() == {"required": True, "authenticated": False}

    for method, path in [
        ("get", "/tasks"), ("get", "/projects"), ("get", "/reminders/due"),
        ("get", "/memory/chat/history"), ("get", "/voice/status"), ("get", "/routines/due"),
        ("post", "/voice/wake"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_login_sets_a_session_cookie(client, db, locked):
    assert client.post("/auth/login", json={"passcode": "wrong"}).status_code == 401

    response = client.post("/auth/login", json={"passcode": "open sesame"}, headers={"user-agent": "test-phone"})

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "jarvis_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/tasks").status_code == 200
    assert client.get("/auth/status").json()["authenticated"] is True

    # Only a hash is stored.
    session = db.query(AuthSession).filter_by(user_agent="test-phone").one()
    assert session.token_hash != client.cookies.get("jarvis_session") and len(session.token_hash) == 64


def test_logout_ends_the_session(client, locked):
    client.post("/auth/login", json={"passcode": "open sesame"})
    token = client.cookies.get("jarvis_session")

    client.post("/auth/logout")

    client.cookies.set("jarvis_session", token)  # a copied cookie no longer works
    assert client.get("/tasks").status_code == 401


def test_expired_and_forged_sessions_are_refused(client, db, locked):
    client.post("/auth/login", json={"passcode": "open sesame"})
    db.query(AuthSession).update({"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    db.commit()
    AuthService._cache.clear()

    assert client.get("/tasks").status_code == 401

    client.cookies.set("jarvis_session", "made-up")
    assert client.get("/tasks").status_code == 401


def test_api_token_for_scripts(client, locked, monkeypatch):
    assert client.get("/tasks", headers={"authorization": "Bearer anything"}).status_code == 401

    monkeypatch.setenv("JARVIS_API_TOKEN", "script-token")

    assert client.get("/tasks", headers={"authorization": "Bearer script-token"}).status_code == 200
    assert client.get("/tasks", headers={"authorization": "Bearer nope"}).status_code == 401
    assert client.get("/tasks", headers={"authorization": "script-token"}).status_code == 401


def test_repeated_wrong_passcodes_lock_logins(client, locked):
    for _ in range(AuthService.MAX_FAILURES):
        assert client.post("/auth/login", json={"passcode": "guess"}).status_code == 401

    blocked = client.post("/auth/login", json={"passcode": "open sesame"})

    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
