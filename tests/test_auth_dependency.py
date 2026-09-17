from uuid import uuid4, UUID
from unittest.mock import Mock

import pytest

from app.authentication import (
    AuthenticationError,
    get_current_user_id,
)

def create_request():
    request = Mock()
    request.session = {}
    return request


@pytest.mark.anyio
async def test_missing_authorization_header_is_rejected():
    request = create_request()

    with pytest.raises(AuthenticationError):
        await get_current_user_id(
            request=request,
            authorization=None,
        )


@pytest.mark.anyio
async def test_invalid_authorization_scheme_is_rejected():
    request = create_request()

    with pytest.raises(AuthenticationError):
        await get_current_user_id(
            request=request,
            authorization="Basic test-token",
        )


@pytest.mark.anyio
async def test_empty_bearer_token_is_rejected():
    request = create_request()

    with pytest.raises(AuthenticationError):
        await get_current_user_id(
            request=request,
            authorization="Bearer ",
        )


@pytest.mark.anyio
async def test_invalid_token_is_rejected():
    request = create_request()

    with pytest.raises(AuthenticationError):
        await get_current_user_id(
            request=request,
            authorization="Bearer invalid-token",
        )


@pytest.mark.anyio
async def test_valid_test_token_returns_user_id():
    request = create_request()

    user_id = await get_current_user_id(
        request=request,
        authorization="Bearer test-token",
    )

    assert user_id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )

    
@pytest.mark.anyio
async def test_session_authentication_returns_user_id():
    user_id = uuid4()

    request = Mock()
    request.session = {
        "user_id": str(user_id),
    }

    result = await get_current_user_id(
        request=request,
        authorization=None,
    )

    assert result == user_id


@pytest.mark.anyio
async def test_invalid_session_user_id_is_rejected():
    request = Mock()
    request.session = {
        "user_id": "not-a-uuid",
    }

    with pytest.raises(AuthenticationError, match="Invalid session user ID"):
        await get_current_user_id(
            request=request,
            authorization=None,
        )