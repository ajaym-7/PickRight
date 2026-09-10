import pytest
from uuid import UUID

from app.authentication import (
    AuthenticationError,
    get_current_user_id,
)


@pytest.mark.anyio
async def test_missing_authorization_header_is_rejected():
    with pytest.raises(AuthenticationError):
        await get_current_user_id(None)


@pytest.mark.anyio
async def test_invalid_authorization_scheme_is_rejected():
    with pytest.raises(AuthenticationError):
        await get_current_user_id("Basic test-token")


@pytest.mark.anyio
async def test_empty_bearer_token_is_rejected():
    with pytest.raises(AuthenticationError):
        await get_current_user_id("Bearer ")


@pytest.mark.anyio
async def test_invalid_token_is_rejected():
    with pytest.raises(AuthenticationError):
        await get_current_user_id("Bearer invalid-token")


@pytest.mark.anyio
async def test_valid_test_token_returns_user_id():
    user_id = await get_current_user_id("Bearer test-token")

    assert user_id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )