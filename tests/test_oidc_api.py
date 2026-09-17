import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.database import SessionLocal, engine

from app.main import app
from uuid import UUID


@pytest.mark.anyio
async def test_auth_login_redirects_to_oidc_provider(monkeypatch):
    async def mock_authorization_url(state, nonce):
        return (
            "https://example.com/authorize"
            f"?state={state}&nonce={nonce}"
        )

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/login",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://example.com/authorize"
    )


@pytest.mark.anyio
async def test_auth_login_stores_state_and_nonce(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce

        return "https://example.com/authorize"

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/login",
            follow_redirects=False,
        )

        assert response.status_code == 302

        session_cookie = response.cookies.get("session")

    assert session_cookie is not None
    assert captured["state"]
    assert captured["nonce"]
    assert captured["state"] != captured["nonce"]

@pytest.mark.anyio
async def test_auth_callback_rejects_missing_state():
    with TestClient(app) as client:
        response = client.get(
            "/auth/callback?code=test-code",
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid OAuth state"


@pytest.mark.anyio
async def test_auth_callback_rejects_invalid_state(monkeypatch):
    async def mock_authorization_url(state, nonce):
        return "https://example.com/authorize"

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/login",
            follow_redirects=False,
        )

        assert response.status_code == 302

        response = client.get(
            "/auth/callback"
            "?code=test-code"
            "&state=attacker-state",
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid OAuth state"


@pytest.mark.anyio
async def test_auth_callback_rejects_missing_code(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        return "https://example.com/authorize"

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )

    with TestClient(app) as client:
        client.get(
            "/auth/login",
            follow_redirects=False,
        )

        response = client.get(
            f"/auth/callback?state={captured['state']}",
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authorization code missing"


@pytest.mark.anyio
async def test_auth_callback_validates_token(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        assert code == "test-code"
        return {
            "id_token": "fake-id-token",
        }

    async def mock_validate_id_token(token, nonce):
        assert token["id_token"] == "fake-id-token"
        assert nonce == captured["nonce"]

        return {
            "sub": "provider-user-123",
            "email": "user@example.com",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )

    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )

    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        client.get(
            "/auth/login",
            follow_redirects=False,
        )

        response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

    assert response.status_code == 200
    body = response.json()

    assert body["email"] == "user@example.com"
    assert body["user_id"] != "provider-user-123"

    UUID(body["user_id"])


@pytest.mark.anyio
async def test_auth_callback_state_is_single_use(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        return {"id_token": "fake-id-token"}

    async def mock_validate_id_token(token, nonce):
        return {
            "sub": "provider-user-123",
            "email": "user@example.com",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )
    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )
    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        client.get(
            "/auth/login",
            follow_redirects=False,
        )

        first = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

        second = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["detail"] == "Invalid OAuth state"


@pytest.mark.anyio
async def test_auth_callback_creates_internal_user(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        return {"id_token": "fake-id-token"}

    async def mock_validate_id_token(token, nonce):
        return {
            "sub": "google-user-123",
            "email": "google-user@example.com",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )
    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )
    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        client.get("/auth/login", follow_redirects=False)

        response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

    assert response.status_code == 200

    body = response.json()

    assert body["email"] == "google-user@example.com"
    assert body["user_id"] != "google-user-123"


@pytest.mark.anyio
async def test_auth_callback_reuses_existing_user(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        return {"id_token": "fake-id-token"}

    async def mock_validate_id_token(token, nonce):
        return {
            "sub": "google-user-reused",
            "email": "reused@example.com",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )
    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )
    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        first_login = client.get(
            "/auth/login",
            follow_redirects=False,
        )

        first_state = captured["state"]

        first_response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={first_state}",
        )

        first_user_id = first_response.json()["user_id"]

        second_login = client.get(
            "/auth/login",
            follow_redirects=False,
        )

        second_state = captured["state"]

        second_response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={second_state}",
        )

        second_user_id = second_response.json()["user_id"]

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_user_id == second_user_id


@pytest.mark.anyio
async def test_auth_callback_stores_google_identity(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        return {"id_token": "fake-id-token"}

    async def mock_validate_id_token(token, nonce):
        return {
            "sub": "google-db-test-user",
            "email": "google-db-test@example.com",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )
    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )
    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/login",
            follow_redirects=False,
        )

        response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

    assert response.status_code == 200

    user_id = response.json()["user_id"]

    await engine.dispose()
    session = SessionLocal()

    try:
        result = await session.execute(
            text("""
                SELECT
                    id,
                    email,
                    oauth_provider,
                    provider_user_id
                FROM users
                WHERE id = :user_id
            """),
            {"user_id": user_id},
        )

        user = result.mappings().one()

        assert str(user["id"]) == user_id
        assert user["email"] == "google-db-test@example.com"
        assert user["oauth_provider"] == "google"
        assert user["provider_user_id"] == "google-db-test-user"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_auth_callback_rejects_missing_email(monkeypatch):
    captured = {}

    async def mock_authorization_url(state, nonce):
        captured["state"] = state
        captured["nonce"] = nonce
        return "https://example.com/authorize"

    async def mock_exchange_code(code):
        return {"id_token": "fake-id-token"}

    async def mock_validate_id_token(token, nonce):
        return {
            "sub": "google-no-email",
        }

    monkeypatch.setattr(
        "app.main.create_authorization_url",
        mock_authorization_url,
    )
    monkeypatch.setattr(
        "app.main.exchange_code_for_token",
        mock_exchange_code,
    )
    monkeypatch.setattr(
        "app.main.validate_id_token",
        mock_validate_id_token,
    )

    with TestClient(app) as client:
        client.get("/auth/login", follow_redirects=False)

        response = client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={captured['state']}",
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication data"