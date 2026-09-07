from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
) 

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
)

SessionLocal = async_sessionmaker(
    bind= engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session

async def check_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return True

    except Exception:
        return False