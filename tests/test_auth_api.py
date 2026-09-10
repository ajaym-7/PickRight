import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_vote_without_authorization_returns_401():
    response = client.post(
        "/polls/00000000-0000-0000-0000-000000000001/vote",
        json={
            "option_id": "00000000-0000-0000-0000-000000000002",
            "ballot_id": "00000000-0000-0000-0000-000000000003",
        },
    )

    assert response.status_code == 401


def test_vote_with_invalid_token_returns_401():
    response = client.post(
        "/polls/00000000-0000-0000-0000-000000000001/vote",
        headers={"Authorization": "Bearer invalid-token"},
        json={
            "option_id": "00000000-0000-0000-0000-000000000002",
            "ballot_id": "00000000-0000-0000-0000-000000000003",
        },
    )

    assert response.status_code == 401


def test_vote_with_valid_token_reaches_voting_layer():
    response = client.post(
        "/polls/00000000-0000-0000-0000-000000000001/vote",
        headers={"Authorization": "Bearer test-token"},
        json={
            "option_id": "00000000-0000-0000-0000-000000000002",
            "ballot_id": "00000000-0000-0000-0000-000000000003",
        },
    )

    # Authentication succeeded, so this must NOT be 401.
    assert response.status_code != 401