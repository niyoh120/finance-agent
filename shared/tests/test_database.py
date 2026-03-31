import asyncio

from sqlalchemy.exc import DBAPIError, DisconnectionError

import shared.database as database


class FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


def test_create_engine_instance_enables_pre_ping_and_pool_recycle(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_async_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("FA_DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
    monkeypatch.setenv("FA_DB_POOL_RECYCLE_SECONDS", "321")
    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)

    database.create_engine_instance()

    assert captured["url"] == "postgresql+asyncpg://user:pass@localhost/db"
    assert captured["pool_pre_ping"] is True
    assert captured["pool_recycle"] == 321


def test_reset_engine_disposes_current_engine_and_clears_singletons() -> None:
    engine = FakeEngine()
    database._engine = engine
    database._session_maker = object()

    asyncio.run(database.reset_engine())

    assert engine.dispose_calls == 1
    assert database._engine is None
    assert database._session_maker is None


def test_is_disconnect_error_recognizes_invalidated_dbapi_error() -> None:
    error = DBAPIError.instance("SELECT 1", {}, OSError("socket closed"), Exception)
    error.connection_invalidated = True

    assert database.is_disconnect_error(error) is True
    assert database.is_disconnect_error(DisconnectionError()) is True
    assert database.is_disconnect_error(RuntimeError("boom")) is False
