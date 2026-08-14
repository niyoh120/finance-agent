from contextlib import asynccontextmanager

import pytest
import shared.database as database


@pytest.mark.asyncio
async def test_safe_session_scope_yields_session_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_session_scope():
        events.append("enter")
        try:
            yield "fake_session"
        finally:
            events.append("exit")

    monkeypatch.setattr(database, "session_scope", fake_session_scope)

    async with database.safe_session_scope() as session:
        events.append(f"use:{session}")

    assert events == ["enter", "use:fake_session", "exit"]


@pytest.mark.asyncio
async def test_safe_session_scope_resets_engine_on_disconnect_error_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_calls = 0

    async def fake_reset_engine() -> None:
        nonlocal reset_calls
        reset_calls += 1

    @asynccontextmanager
    async def fake_session_scope():
        yield "fake_session"

    monkeypatch.setattr(database, "reset_engine", fake_reset_engine)
    monkeypatch.setattr(database, "session_scope", fake_session_scope)
    monkeypatch.setattr(database, "is_disconnect_error", lambda e: isinstance(e, RuntimeError), raising=False)

    with pytest.raises(RuntimeError, match="disconnect"):
        async with database.safe_session_scope() as _:
            raise RuntimeError("disconnect")

    assert reset_calls == 1


@pytest.mark.asyncio
async def test_safe_session_scope_does_not_reset_engine_on_normal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_calls = 0

    async def fake_reset_engine() -> None:
        nonlocal reset_calls
        reset_calls += 1

    @asynccontextmanager
    async def fake_session_scope():
        yield "fake_session"

    monkeypatch.setattr(database, "reset_engine", fake_reset_engine)
    monkeypatch.setattr(database, "session_scope", fake_session_scope)
    monkeypatch.setattr(database, "is_disconnect_error", lambda e: False, raising=False)

    with pytest.raises(ValueError, match="normal"):
        async with database.safe_session_scope() as _:
            raise ValueError("normal")

    assert reset_calls == 0
