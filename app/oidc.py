from typing import Any
import secrets

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client

from app.config import get_settings

from urllib.parse import urlencode

from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.jws import JWSRegistry
from joserfc.errors import InvalidKeyIdError


settings = get_settings()


def create_oidc_client() -> AsyncOAuth2Client:
    """Create an OAuth2 client configured for the OIDC provider."""

    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
    )


async def fetch_oidc_discovery() -> dict[str, Any]:
    """Fetch the OIDC provider discovery document."""

    if not settings.oidc_discovery_url:
        raise ValueError("OIDC discovery URL is not configured")

    async with httpx.AsyncClient() as client:
        response = await client.get(settings.oidc_discovery_url)
        response.raise_for_status()

        discovery = response.json()

    required_fields = {
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
    }

    missing_fields = required_fields - discovery.keys()

    if missing_fields:
        raise ValueError(
            f"OIDC discovery document missing fields: {sorted(missing_fields)}"
        )

    return discovery


def generate_state() -> str:
    """Generate a cryptographically secure OAuth state value."""

    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """Generate a cryptographically secure OIDC nonce."""

    return secrets.token_urlsafe(32)

async def create_authorization_url(
    state: str,
    nonce: str,
) -> str:
    """Create the OIDC authorization URL."""

    discovery = await fetch_oidc_discovery()

    params = {
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
    }

    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"

async def exchange_code_for_token(
    code: str,
) -> dict[str, Any]:
    """Exchange an authorization code for OIDC tokens."""

    if not code:
        raise ValueError("Authorization code is required")

    discovery = await fetch_oidc_discovery()

    client = create_oidc_client()

    token = await client.fetch_token(
        discovery["token_endpoint"],
        code=code,
    )

    return token

async def fetch_oidc_jwks() -> dict[str, Any]:
    """Fetch the OIDC provider's JSON Web Key Set."""

    discovery = await fetch_oidc_discovery()

    async with httpx.AsyncClient() as client:
        response = await client.get(discovery["jwks_uri"])
        response.raise_for_status()

        jwks = response.json()

    if "keys" not in jwks:
        raise ValueError("OIDC JWKS response missing keys")

    return jwks


async def validate_id_token(
    token: dict[str, Any],
    nonce: str,
) -> dict[str, Any]:
    """Validate an OIDC ID token and return its trusted claims."""

    if "id_token" not in token:
        raise ValueError("OIDC token response missing id_token")

    if not nonce:
        raise ValueError("OIDC nonce is required")

    discovery = await fetch_oidc_discovery()
    jwks = await fetch_oidc_jwks()

    claims_options = {
        "iss": {
            "values": [discovery["issuer"]],
        },
    }

    claims_params = {
        "nonce": nonce,
        "client_id": settings.oidc_client_id,
    }

    algorithms = discovery.get(
        "id_token_signing_alg_values_supported"
    )

    key_set = KeySet.import_key_set(jwks)

    try:
        decoded = jwt.decode(
            token["id_token"],
            key=key_set,
            registry=JWSRegistry(
                algorithms=algorithms,
                strict_check_header=False,
            ),
        )
    except InvalidKeyIdError:
        jwks = await fetch_oidc_jwks()
        key_set = KeySet.import_key_set(jwks)

        decoded = jwt.decode(
            token["id_token"],
            key=key_set,
            registry=JWSRegistry(
                algorithms=algorithms,
                strict_check_header=False,
            ),
        )

    claims = CodeIDToken(
        decoded.claims,
        decoded.header,
        claims_options,
        claims_params,
    )

    claims.validate(leeway=120)

    if not claims.get("sub"):
        raise ValueError("OIDC ID token missing subject")

    return dict(claims)