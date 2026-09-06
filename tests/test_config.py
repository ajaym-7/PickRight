from app.config import Settings
import pytest
from pydantic import ValidationError

def test_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5432/pickright",
    )

    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.redis_url == "redis://localhost:6379/0"

def test_database_url_is_required(monkeypatch):

    with pytest.raises(ValidationError):
        Settings(_env_file=None)