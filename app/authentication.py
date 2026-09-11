from uuid import UUID

from fastapi import Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AuthenticationError(Exception):
    """Raised when authentication fails."""


async def get_or_create_user(
    session: AsyncSession,
    provider: str,
    provider_user_id: str,
    email: str,
) -> UUID:
    """Resolve an OAuth identity to an internal user ID."""

    if not provider or not provider_user_id or not email:
        raise AuthenticationError("Invalid authentication data")

    result = await session.execute(
        text("""
            INSERT INTO users (
                email,
                oauth_provider,
                provider_user_id
            )
            VALUES (
                :email,
                :provider,
                :provider_user_id
            )
            ON CONFLICT (oauth_provider, provider_user_id)
            DO NOTHING
            RETURNING id
        """),
        {
            "email": email,
            "provider": provider,
            "provider_user_id": provider_user_id,
        },
    )

    user_id = result.scalar_one_or_none()

    if user_id is not None:
        await session.commit()
        return user_id

    existing_user = (
        await session.execute(
            text("""
                SELECT id
                FROM users
                WHERE oauth_provider = :provider
                  AND provider_user_id = :provider_user_id
            """),
            {
                "provider": provider,
                "provider_user_id": provider_user_id,
            },
        )
    ).scalar_one()

    await session.commit()

    return existing_user

async def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> UUID:
    """
    Resolve the authenticated user from the Authorization header.

    Temporary authentication mechanism.
    Real OAuth token validation will replace this.
    """

    if authorization is None:
        raise AuthenticationError("Authentication required")

    if not authorization.startswith("Bearer "):
        raise AuthenticationError("Invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise AuthenticationError("Authentication required")

    # Temporary development token.
    if token != "test-token":
        raise AuthenticationError("Invalid authentication token")

    return UUID("00000000-0000-0000-0000-000000000001")