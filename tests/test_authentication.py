import pytest
from sqlalchemy import text
from uuid import uuid4

from app.authentication import (
    AuthenticationError,
    get_or_create_user,
)
from app.database import SessionLocal, engine

@pytest.mark.anyio
async def test_get_or_create_user_creates_user():
    await engine.dispose()
    session = SessionLocal()

    suffix = uuid4()

    try:
        user_id = await get_or_create_user(
            session=session,
            provider="test",
            provider_user_id=f"auth-test-user-{suffix}",
            email=f"auth-test-{suffix}@example.com",
    )
        
        result = await session.execute(
            text("""
                SELECT id, email, oauth_provider, provider_user_id
                FROM users
                WHERE id = :user_id
            """),
            {"user_id": user_id},
        )

        user = result.mappings().one()

        assert user["id"] == user_id
        assert user["email"] == f"auth-test-{suffix}@example.com"
        assert user["oauth_provider"] == "test"
        assert user["provider_user_id"] == f"auth-test-user-{suffix}"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_existing_oauth_identity_returns_same_user():
    await engine.dispose()
    session = SessionLocal()

    try:
        suffix = uuid4()

        first_user_id = await get_or_create_user(
            session=session,
            provider="test",
            provider_user_id=f"same-user-{suffix}",
            email=f"same-user-{suffix}@example.com",
        )

        second_user_id = await get_or_create_user(
            session=session,
            provider="test",
            provider_user_id=f"same-user-{suffix}",
            email=f"different-email-{suffix}@example.com",
        )

        assert second_user_id == first_user_id

    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_different_oauth_identities_create_different_users():
    await engine.dispose()
    session = SessionLocal()

    try:
        suffix = uuid4()

        first_user_id = await get_or_create_user(
            session=session,
            provider="test",
            provider_user_id=f"user-one-{suffix}",
            email=f"user-one-{suffix}@example.com",
        )

        second_user_id = await get_or_create_user(
            session=session,
            provider="test",
            provider_user_id=f"user-two-{suffix}",
            email=f"user-two-{suffix}@example.com",
        )

        assert first_user_id != second_user_id

    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.anyio
async def test_missing_authentication_data_is_rejected():
    await engine.dispose()
    session = SessionLocal()

    try:
        with pytest.raises(AuthenticationError):
            await get_or_create_user(
                session=session,
                provider="",
                provider_user_id="user",
                email="user@example.com",
            )

    finally:
        await session.close()
        await engine.dispose()