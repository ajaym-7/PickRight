import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from uuid import uuid4

from app.main import app, get_current_user_id


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