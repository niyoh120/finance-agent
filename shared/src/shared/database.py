import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Callable, Awaitable, TypeVar

from sqlalchemy.exc import DBAPIError, DisconnectionError, InvalidatePoolError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

R = TypeVar("R")
T = TypeVar("T")
W = TypeVar("W")

DEFAULT_POOL_RECYCLE_SECONDS = 1800
_engine_reset_lock = asyncio.Lock()


def get_database_url() -> str:
    url = os.getenv("FA_DATABASE_URL")
    if not url:
        raise ValueError("FA_DATABASE_URL environment variable is not set")
    return url


def get_pool_recycle_seconds() -> int:
    return int(os.getenv("FA_DB_POOL_RECYCLE_SECONDS", str(DEFAULT_POOL_RECYCLE_SECONDS)))


def create_engine_instance() -> AsyncEngine:
    return create_async_engine(
        get_database_url(),
        echo=os.getenv("FA_SQL_ECHO", "false").lower() == "true",
        pool_pre_ping=True,
        pool_recycle=get_pool_recycle_seconds(),
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


def is_disconnect_error(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError):
        return exc.connection_invalidated
    return isinstance(exc, (DisconnectionError, InvalidatePoolError))


async def reset_engine() -> None:
    global _engine, _session_maker

    async with _engine_reset_lock:
        engine = _engine
        _engine = None
        _session_maker = None
        if engine is not None:
            await engine.dispose()


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


@asynccontextmanager
async def safe_session_scope() -> AsyncGenerator[AsyncSession, None]:
    try:
        async with session_scope() as session:
            yield session
    except Exception as exc:
        if is_disconnect_error(exc):
            logger.warning("Database connection invalidated, resetting engine")
            await reset_engine()
        raise


async def run_around_db(
    read_fn: Callable[[AsyncSession], Awaitable[R]],
    io_fn: Callable[[R], Awaitable[T]],
    write_fn: Callable[[AsyncSession, T], Awaitable[W]],
) -> W:
    async with safe_session_scope() as read_session:
        read_result = await read_fn(read_session)

    io_result = await io_fn(read_result)

    async with safe_session_scope() as write_session:
        return await write_fn(write_session, io_result)
