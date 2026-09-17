import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.config import get_settings
from app.oidc import (
    create_authorization_url,
    exchange_code_for_token,
    fetch_oidc_discovery,
    fetch_oidc_jwks,
    generate_nonce,
    generate_state,
    validate_id_token,
)


@pytest.mark.anyio
async def test_fetch_oidc_discovery(monkeypatch):
    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "issuer": "https://example.com",
                "authorization_endpoint": "https://example.com/authorize",
                "token_endpoint": "https://example.com/token",
                "jwks_uri": "https://example.com/jwks",
            }

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get(self, url):
            assert url == "https://example.com/.well-known/openid-configuration"
            return MockResponse()

    monkeypatch.setattr(
        "app.oidc.httpx.AsyncClient",
        lambda: MockClient(),
    )

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "oidc_discovery_url",
        "https://example.com/.well-known/openid-configuration",
    )

    discovery = await fetch_oidc_discovery()

    assert discovery["issuer"] == "https://example.com"
    assert discovery["authorization_endpoint"].endswith("/authorize")
    assert discovery["token_endpoint"].endswith("/token")
    assert discovery["jwks_uri"].endswith("/jwks")


@pytest.mark.anyio
async def test_discovery_requires_configuration(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_discovery_url", "")

    with pytest.raises(ValueError, match="OIDC discovery URL is not configured"):
        await fetch_oidc_discovery()

def test_generate_state_is_unique():
    first = generate_state()
    second = generate_state()

    assert first != second
    assert len(first) >= 32


def test_generate_nonce_is_unique():
    first = generate_nonce()
    second = generate_nonce()

    assert first != second
    assert len(first) >= 32


@pytest.mark.anyio
async def test_create_authorization_url(monkeypatch):
    from app.config import get_settings

    settings = get_settings()

    monkeypatch.setattr(
        settings,
        "oidc_client_id",
        "test-client-id",
    )

    monkeypatch.setattr(
        settings,
        "oidc_redirect_uri",
        "http://localhost:8000/auth/callback",
    )

    async def mock_discovery():
        return {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "jwks_uri": "https://example.com/jwks",
        }

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_discovery",
        mock_discovery,
    )

    url = await create_authorization_url(
        state="test-state",
        nonce="test-nonce",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "example.com"
    assert parsed.path == "/authorize"

    assert params["client_id"] == ["test-client-id"]
    assert params["redirect_uri"] == [
        "http://localhost:8000/auth/callback"
    ]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email profile"]
    assert params["state"] == ["test-state"]
    assert params["nonce"] == ["test-nonce"]


@pytest.mark.anyio
async def test_exchange_code_requires_code():
    with pytest.raises(
        ValueError,
        match="Authorization code is required",
    ):
        await exchange_code_for_token("")


@pytest.mark.anyio
async def test_exchange_code_for_token(monkeypatch):
    from app.config import get_settings

    settings = get_settings()

    monkeypatch.setattr(
        settings,
        "oidc_discovery_url",
        "https://example.com/.well-known/openid-configuration",
    )

    async def mock_discovery():
        return {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "jwks_uri": "https://example.com/jwks",
        }

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_discovery",
        mock_discovery,
    )

    class MockClient:
        async def fetch_token(self, endpoint, code):
            assert endpoint == "https://example.com/token"
            assert code == "test-authorization-code"

            return {
                "access_token": "test-access-token",
                "id_token": "test-id-token",
                "token_type": "Bearer",
            }

    monkeypatch.setattr(
        "app.oidc.create_oidc_client",
        lambda: MockClient(),
    )

    token = await exchange_code_for_token(
        "test-authorization-code"
    )

    assert token["access_token"] == "test-access-token"
    assert token["id_token"] == "test-id-token"


@pytest.mark.anyio
async def test_fetch_oidc_jwks(monkeypatch):
    async def mock_discovery():
        return {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "jwks_uri": "https://example.com/jwks",
        }

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_discovery",
        mock_discovery,
    )

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "keys": [
                    {
                        "kty": "RSA",
                        "kid": "test-key",
                    }
                ]
            }

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get(self, url):
            assert url == "https://example.com/jwks"
            return MockResponse()

    monkeypatch.setattr(
        "app.oidc.httpx.AsyncClient",
        lambda: MockClient(),
    )

    jwks = await fetch_oidc_jwks()

    assert "keys" in jwks
    assert jwks["keys"][0]["kid"] == "test-key"


@pytest.mark.anyio
async def test_fetch_oidc_jwks_requires_keys(monkeypatch):
    async def mock_discovery():
        return {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "jwks_uri": "https://example.com/jwks",
        }

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_discovery",
        mock_discovery,
    )

    class MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    class MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get(self, url):
            return MockResponse()

    monkeypatch.setattr(
        "app.oidc.httpx.AsyncClient",
        lambda: MockClient(),
    )

    with pytest.raises(
        ValueError,
        match="OIDC JWKS response missing keys",
    ):
        await fetch_oidc_jwks()


def create_test_key_pair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_key = private_key.public_key()

    public_jwk = RSAKey.import_key(public_key)
    public_jwk_dict = public_jwk.as_dict(is_private=False)
    public_jwk_dict["kid"] = "test-key"

    return private_key, public_jwk_dict


def setup_oidc_mocks(monkeypatch, public_jwk_dict):
    async def mock_discovery():
        return {
            "issuer": "https://example.com",
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "jwks_uri": "https://example.com/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    async def mock_jwks():
        return {
            "keys": [public_jwk_dict],
        }

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_discovery",
        mock_discovery,
    )

    monkeypatch.setattr(
        "app.oidc.fetch_oidc_jwks",
        mock_jwks,
    )

    settings = get_settings()

    monkeypatch.setattr(
        settings,
        "oidc_client_id",
        "test-client-id",
    )


def create_test_id_token(
    private_key,
    *,
    issuer="https://example.com",
    audience="test-client-id",
    nonce="test-nonce",
    subject="user-123",
    expires_in=300,
):
    now = int(time.time())

    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "nonce": nonce,
        "email": "user@example.com",
    }

    header = {
        "alg": "RS256",
        "kid": "test-key",
    }

    private_jwk = RSAKey.import_key(private_key)

    return jwt.encode(
        header,
        claims,
        private_jwk,
    )


@pytest.mark.anyio
async def test_validate_id_token(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        nonce="test-nonce",
    )

    claims = await validate_id_token(
        {"id_token": id_token},
        nonce="test-nonce",
    )

    assert claims["sub"] == "user-123"
    assert claims["email"] == "user@example.com"
    assert claims["iss"] == "https://example.com"


@pytest.mark.anyio
async def test_validate_id_token_rejects_wrong_issuer(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        issuer="https://attacker.example.com",
        nonce="test-nonce",
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="test-nonce",
        )


@pytest.mark.anyio
async def test_validate_id_token_rejects_wrong_audience(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        audience="attacker-client-id",
        nonce="test-nonce",
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="test-nonce",
        )


@pytest.mark.anyio
async def test_validate_id_token_rejects_wrong_nonce(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        nonce="original-nonce",
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="different-nonce",
        )

@pytest.mark.anyio
async def test_validate_id_token_rejects_expired_token(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        nonce="test-nonce",
        expires_in=-300,
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="test-nonce",
        )

@pytest.mark.anyio
async def test_validate_id_token_rejects_missing_subject(monkeypatch):
    private_key, public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        public_jwk_dict,
    )

    id_token = create_test_id_token(
        private_key,
        nonce="test-nonce",
        subject="",
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="test-nonce",
        )

@pytest.mark.anyio
async def test_validate_id_token_rejects_tampered_signature(monkeypatch):
    trusted_private_key, trusted_public_jwk_dict = create_test_key_pair()

    setup_oidc_mocks(
        monkeypatch,
        trusted_public_jwk_dict,
    )

    attacker_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    id_token = create_test_id_token(
        attacker_private_key,
        nonce="test-nonce",
    )

    with pytest.raises(Exception):
        await validate_id_token(
            {"id_token": id_token},
            nonce="test-nonce",
        )