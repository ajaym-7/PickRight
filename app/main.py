from fastapi import FastAPI

from contextlib import asynccontextmanager

from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import engine, check_database


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
