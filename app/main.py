from fastapi import FastAPI, Depends, HTTPException
from uuid import UUID

from contextlib import asynccontextmanager

from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import engine, check_database, get_db
from app.schema import VoteRequest, VoteResponse
from app.voting import cast_vote

from app.exceptions import (
    AlreadyVotedError,
    BallotIdConflictError,
    BallotStateMissingError,
    InvalidOptionError,
    PollNotOpenError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)


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


def get_current_user_id() -> UUID:
    # Temporary authentication placeholder.
    # OAuth/authentication will replace this later.
    return UUID("00000000-0000-0000-0000-000000000001")

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