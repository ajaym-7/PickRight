import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from uuid import uuid4

from app.main import app, get_current_user_id
from app.database import SessionLocal



async def make_client(user_id):
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    transport = ASGITransport(app=app)

    return AsyncClient(
        transport=transport,
        base_url="http://test",
    )


@pytest.mark.anyio
async def test_vote_endpoint_success(voting_setup):
    _, user_id, poll_id, option_id = voting_setup

    client = await make_client(user_id)

    try:
        async with client:
            response = await client.post(
                f"/polls/{poll_id}/vote",
                json={"option_id": str(option_id)},
            )

        assert response.status_code == 200

        body = response.json()
        assert "ballot_id" in body

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_rejects_duplicate_vote(voting_setup):
    _, user_id, poll_id, option_id = voting_setup

    client = await make_client(user_id)

    try:
        async with client:
            first = await client.post(
                f"/polls/{poll_id}/vote",
                json={"option_id": str(option_id)},
            )

            second = await client.post(
                f"/polls/{poll_id}/vote",
                json={"option_id": str(option_id)},
            )

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["detail"] == (
            "User has already voted or is not eligible"
        )

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_rejects_invalid_option(voting_setup):
    _, user_id, poll_id, _ = voting_setup

    invalid_option_id = "00000000-0000-0000-0000-000000000099"

    client = await make_client(user_id)

    try:
        async with client:
            response = await client.post(
                f"/polls/{poll_id}/vote",
                json={"option_id": invalid_option_id},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Option does not belong to poll"
        )

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_rejects_closed_poll(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await session.execute(
        text("""
            UPDATE polls
            SET status = 'closed'
            WHERE id = :poll_id
        """),
        {"poll_id": poll_id},
    )

    await session.commit()

    client = await make_client(user_id)

    try:
        async with client:
            response = await client.post(
                f"/polls/{poll_id}/vote",
                json={"option_id": str(option_id)},
            )

        assert response.status_code == 409
        assert response.json()["detail"] == "Poll is not open"

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_is_idempotent(voting_setup):
    _, user_id, poll_id, option_id = voting_setup

    ballot_id = str(uuid4())

    client = await make_client(user_id)

    try:
        async with client:
            first = await client.post(
                f"/polls/{poll_id}/vote",
                json={
                    "option_id": str(option_id),
                    "ballot_id": ballot_id,
                },
            )

            second = await client.post(
                f"/polls/{poll_id}/vote",
                json={
                    "option_id": str(option_id),
                    "ballot_id": ballot_id,
                },
            )

        assert first.status_code == 200
        assert second.status_code == 200

        assert first.json()["ballot_id"] == ballot_id
        assert second.json()["ballot_id"] == ballot_id

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_rejects_ballot_id_conflict(voting_setup):
    _, user_id, poll_id, option_id = voting_setup

    ballot_id = str(uuid4())

    client = await make_client(user_id)

    try:
        async with client:
            first = await client.post(
                f"/polls/{poll_id}/vote",
                json={
                    "option_id": str(option_id),
                    "ballot_id": ballot_id,
                },
            )

            second = await client.post(
                f"/polls/{poll_id}/vote",
                json={
                    "option_id": "00000000-0000-0000-0000-000000000099",
                    "ballot_id": ballot_id,
                },
            )

        assert first.status_code == 200

        assert second.status_code == 409
        assert second.json()["detail"] == (
            "Ballot ID already used with different payload"
        )

    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_vote_endpoint_uses_oidc_session(
    voting_setup,
    monkeypatch,
):
    _, user_id, poll_id, option_id = voting_setup

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
            "sub": "session-test-provider-user",
            "email": "session-test@example.com",
        }

    async def mock_get_or_create_user(
        session,
        provider,
        provider_user_id,
        email,
    ):
        assert provider == "google"
        assert provider_user_id == "session-test-provider-user"
        assert email == "session-test@example.com"

        return user_id

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

    monkeypatch.setattr(
        "app.main.get_or_create_user",
        mock_get_or_create_user,
    )

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:

        # Establish the OIDC application session.
        login_response = await client.get(
            "/auth/login",
            follow_redirects=False,
        )

        assert login_response.status_code == 302

        state = captured["state"]

        callback_response = await client.get(
            f"/auth/callback"
            f"?code=test-code"
            f"&state={state}",
        )

        assert callback_response.status_code == 200

        body = callback_response.json()

        assert body["user_id"] == str(user_id)

        # Do NOT provide an Authorization header.
        # Authentication must come from the OIDC session.
        vote_response = await client.post(
            f"/polls/{poll_id}/vote",
            json={
                "option_id": str(option_id),
            },
        )

    assert vote_response.status_code == 200
    assert "ballot_id" in vote_response.json()