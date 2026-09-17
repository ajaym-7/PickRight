from fastapi import FastAPI, Depends, HTTPException
from uuid import UUID

from contextlib import asynccontextmanager

from fastapi.responses import JSONResponse
from sqlalchemy import text

from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, check_database, get_db
from app.schema import VoteRequest, VoteResponse
from app.voting import cast_vote
from app.config import get_settings

from app.exceptions import (
    AlreadyVotedError,
    BallotIdConflictError,
    BallotStateMissingError,
    InvalidOptionError,
    PollNotOpenError,
)

from app.authentication import (
    AuthenticationError,
    get_current_user_id,
    get_or_create_user,
)

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.oidc import (
    create_authorization_url,
    exchange_code_for_token,
    generate_nonce,
    generate_state,
    validate_id_token,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=get_settings().session_secret,
    https_only=False,
    # for production change to True
)

from app.oidc import (
    create_authorization_url,
    generate_nonce,
    generate_state,
)


@app.get("/")
def hello():
    return {"message": "Hello World"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/ready")
async def readiness_check():
    if await check_database():
        return {"status": "ready"}

    
    return JSONResponse(
        status_code=503,
        content={"status": "not ready"},
        )


@app.post(
    "/polls/{poll_id}/vote",
    response_model=VoteResponse,
)
async def vote(
    poll_id: UUID,
    request: VoteRequest,
    session=Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    try:
        ballot_id = await cast_vote(
            session=session,
            user_id=user_id,
            poll_id=poll_id,
            option_id=request.option_id,
            ballot_id=request.ballot_id,
        )

    except PollNotOpenError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    except InvalidOptionError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except AlreadyVotedError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    except BallotIdConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

    except BallotStateMissingError:
        raise HTTPException(
            status_code=500,
            detail="Voting system is not properly initialized",
        )

    return VoteResponse(ballot_id=ballot_id)

@app.exception_handler(AuthenticationError)
async def authentication_exception_handler(request, exc):
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc)},
    )

@app.get("/auth/login")
async def auth_login(request: Request):
    state = generate_state()
    nonce = generate_nonce()

    request.session["oidc_state"] = state
    request.session["oidc_nonce"] = nonce

    authorization_url = await create_authorization_url(
        state=state,
        nonce=nonce,
    )

    return RedirectResponse(
        authorization_url,
        status_code=302,
    )


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    session=Depends(get_db),
):
    expected_state = request.session.pop("oidc_state", None)
    expected_nonce = request.session.pop("oidc_nonce", None)

    if not state or not expected_state or state != expected_state:
        raise AuthenticationError("Invalid OAuth state")

    if not code:
        raise AuthenticationError("Authorization code missing")

    if not expected_nonce:
        raise AuthenticationError("OIDC nonce missing")

    token = await exchange_code_for_token(code)

    claims = await validate_id_token(
        token=token,
        nonce=expected_nonce,
    )

    if not claims.get("sub") or not claims.get("email"):
        raise AuthenticationError("Invalid authentication data")

    user_id = await get_or_create_user(
        session=session,
        provider="google",
        provider_user_id=claims["sub"],
        email=claims["email"],
    )

    request.session["user_id"] = str(user_id)

    return {
        "user_id": str(user_id),
        "email": claims["email"],
    }