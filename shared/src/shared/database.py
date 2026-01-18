import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL environment variable is not set")
    return url


def create_engine_instance() -> AsyncEngine:
    return create_async_engine(
        get_database_url(),
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        pool_pre_ping=True,
    )


_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine_instance()
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        engine = get_engine()
        _session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return _session_maker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastUI/FastAPI or context manager."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone scripts."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
