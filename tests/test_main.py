from fastapi.testclient import TestClient

from unittest.mock import AsyncMock, patch

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready():
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_when_database_unavailable():
    with patch(
        "app.main.check_database",
        new = AsyncMock(return_value= False),
    ):
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}