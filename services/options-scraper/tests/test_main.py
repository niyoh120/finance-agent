import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from types import ModuleType

import pytest

import options_scraper.main as main_module
from options_scraper.main import (
    Settings,
    build_discord_client,
    build_message_content,
    get_resume_cursor,
    load_settings,
)


class DummyField:
    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value


class DummyEmbed:
    def __init__(self, title: str | None, description: str | None, fields: list[DummyField]):
        self.title = title
        self.description = description
        self.fields = fields


class DummyAuthor:
    def __init__(self, name: str):
        self.name = name


class DummyMessage:
    def __init__(self, content: str, embeds: list[DummyEmbed]):
        self.content = content
        self.embeds = embeds
        self.author = DummyAuthor("UW Live Options Flow")
        self.id = 1
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)


class DummyChannel:
    def __init__(self, messages: list[DummyMessage]):
        self._messages = messages

    async def history(self, **_kwargs: object):
        for message in self._messages:
            yield message


def build_fake_client(monkeypatch: pytest.MonkeyPatch, settings: Settings | None = None):
    fake_discord = ModuleType("discord")

    class FakeClient:
        def __init__(self, **kwargs: object):
            self.kwargs = kwargs

        async def wait_until_ready(self) -> None:
            return None

        def get_channel(self, _channel_id: int) -> object | None:
            return getattr(self, "_channel", None)

        def is_closed(self) -> bool:
            sequence = getattr(self, "_closed_sequence", [True])
            if not sequence:
                return True
            return sequence.pop(0)

    fake_discord.Client = FakeClient
    fake_discord.Object = lambda **kwargs: SimpleNamespace(**kwargs)
    fake_discord.utils = type("Utils", (), {"time_snowflake": staticmethod(lambda _dt: 1)})

    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    return build_discord_client(
        settings
        or Settings(
            discord_token="token",
            channel_id=123,
            poll_interval=0,
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
        )
    )


def test_load_settings_requires_token_and_channel_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FA_OPTIONS_SCRAPER_DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("FA_OPTIONS_SCRAPER_CHANNEL_ID", raising=False)

    with pytest.raises(ValueError, match="FA_OPTIONS_SCRAPER_DISCORD_TOKEN"):
        load_settings()


def test_load_settings_parses_start_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FA_OPTIONS_SCRAPER_DISCORD_TOKEN", "token")
    monkeypatch.setenv("FA_OPTIONS_SCRAPER_CHANNEL_ID", "123456")
    monkeypatch.setenv("FA_OPTIONS_SCRAPER_POLL_INTERVAL", "120")
    monkeypatch.setenv("FA_OPTIONS_SCRAPER_START_DATE", "2025-12-01")

    settings = load_settings()

    assert settings == Settings(
        discord_token="token",
        channel_id=123456,
        poll_interval=120,
        start_date=datetime(2025, 12, 1, tzinfo=UTC),
    )


def test_build_message_content_prefers_plain_text() -> None:
    message = DummyMessage(content="plain content", embeds=[])

    assert build_message_content(message) == "plain content"


def test_build_message_content_reconstructs_first_embed() -> None:
    message = DummyMessage(
        content="",
        embeds=[
            DummyEmbed(
                title="Header",
                description="Body",
                fields=[DummyField("Premium", "$120,000"), DummyField("Side", "Ask")],
            )
        ],
    )

    assert build_message_content(message) == "Header\nBody\nPremium: $120,000\nSide: Ask"


def test_build_discord_client_does_not_require_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_discord = ModuleType("discord")

    class FakeClient:
        def __init__(self, **kwargs: object):
            self.kwargs = kwargs

    fake_discord.Client = FakeClient
    fake_discord.Object = object
    fake_discord.utils = type("Utils", (), {"time_snowflake": staticmethod(lambda _dt: 1)})

    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    client = build_discord_client(
        Settings(
            discord_token="token",
            channel_id=123,
            poll_interval=300,
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
        )
    )

    assert isinstance(client, FakeClient)
    assert client.kwargs == {}


def test_build_discord_client_does_not_assign_reserved_settings_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_discord = ModuleType("discord")

    class FakeClient:
        settings = property(lambda self: "reserved")

        def __init__(self, **kwargs: object):
            self.kwargs = kwargs

    fake_discord.Client = FakeClient
    fake_discord.Object = object
    fake_discord.utils = type("Utils", (), {"time_snowflake": staticmethod(lambda _dt: 1)})

    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    client = build_discord_client(
        Settings(
            discord_token="token",
            channel_id=123,
            poll_interval=300,
            start_date=datetime(2025, 12, 1, tzinfo=UTC),
        )
    )

    assert isinstance(client, FakeClient)


def test_get_resume_cursor_prefers_latest_numeric_id_at_latest_timestamp() -> None:
    message_rows = [
        ("1382385274612844543", datetime(2026, 3, 10, 10, 0, tzinfo=UTC)),
        ("options_180b5deb-de6e-4d01-addd-e94d5a1e06de", datetime(2026, 3, 11, 10, 0, tzinfo=UTC)),
        ("1382385274612844545", datetime(2026, 3, 11, 10, 0, tzinfo=UTC)),
    ]

    assert get_resume_cursor(message_rows, lambda dt: 999) == 1382385274612844545


def test_get_resume_cursor_falls_back_to_latest_timestamp_when_latest_id_is_not_numeric() -> None:
    latest_timestamp = datetime(2026, 3, 11, 10, 0, tzinfo=UTC)
    message_rows = [
        ("1382385274612844543", datetime(2026, 3, 10, 10, 0, tzinfo=UTC)),
        ("options_180b5deb-de6e-4d01-addd-e94d5a1e06de", latest_timestamp),
        ("options_5eec5236-3e8b-482a-bca4-f8dd5a1f7c37", latest_timestamp),
    ]

    assert get_resume_cursor(message_rows, lambda dt: 777 if dt == latest_timestamp else 0) == 777


def test_get_resume_cursor_returns_none_when_there_is_no_history() -> None:
    assert get_resume_cursor([], lambda dt: 1) is None


def test_fetch_and_store_reads_cursor_before_history_and_writes_in_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_fake_client(monkeypatch)
    events: list[str] = []
    session_names = iter(["read-session", "write-session"])

    @asynccontextmanager
    async def fake_session_scope():
        session_name = next(session_names)
        events.append(f"enter:{session_name}")
        try:
            yield session_name
        finally:
            events.append(f"exit:{session_name}")

    async def fake_get_resume_cursor(session: object, _time_snowflake) -> int | None:
        events.append(f"cursor:{session}")
        return None

    async def fake_insert_flow(session: object, _data: object) -> None:
        events.append(f"insert:{session}")

    monkeypatch.setattr(main_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(client, "_get_resume_cursor", fake_get_resume_cursor)
    monkeypatch.setattr(client, "_insert_flow", fake_insert_flow)
    monkeypatch.setattr(main_module, "parse_message", lambda *_args: object())

    message = DummyMessage(content="flow", embeds=[])
    channel = DummyChannel([message])

    original_history = channel.history

    async def instrumented_history(**kwargs: object):
        events.append("history:start")
        async for item in original_history(**kwargs):
            yield item

    setattr(channel, "history", instrumented_history)

    asyncio.run(client._fetch_and_store(channel))

    assert events == [
        "enter:read-session",
        "cursor:read-session",
        "exit:read-session",
        "history:start",
        "enter:write-session",
        "insert:write-session",
        "exit:write-session",
    ]


def test_poll_loop_resets_engine_after_disconnect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_fake_client(monkeypatch)
    client._channel = object()
    client._closed_sequence = [False, True]
    disconnect_error = RuntimeError("disconnect")
    reset_calls: list[str] = []

    class FakeDateTime:
        @staticmethod
        def now(_tz) -> datetime:
            return datetime(2026, 3, 30, 10, 0, tzinfo=UTC)

    async def fake_fetch_and_store(_channel: object) -> None:
        raise disconnect_error

    async def fake_reset_engine() -> None:
        reset_calls.append("reset")

    async def fake_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr(main_module, "datetime", FakeDateTime)
    monkeypatch.setattr(client, "_fetch_and_store", fake_fetch_and_store)
    monkeypatch.setattr(main_module, "is_disconnect_error", lambda exc: exc is disconnect_error, raising=False)
    monkeypatch.setattr(main_module, "reset_engine", fake_reset_engine, raising=False)
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    asyncio.run(client._poll_loop())

    assert reset_calls == ["reset"]


def test_fetch_and_store_skips_write_session_when_nothing_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_fake_client(monkeypatch)
    events: list[str] = []

    @asynccontextmanager
    async def fake_session_scope():
        events.append("enter:read-session")
        try:
            yield "read-session"
        finally:
            events.append("exit:read-session")

    async def fake_get_resume_cursor(session: object, _time_snowflake) -> int | None:
        events.append(f"cursor:{session}")
        return None

    monkeypatch.setattr(main_module, "session_scope", fake_session_scope)
    monkeypatch.setattr(client, "_get_resume_cursor", fake_get_resume_cursor)
    monkeypatch.setattr(main_module, "parse_message", lambda *_args: None)

    channel = DummyChannel([DummyMessage(content="flow", embeds=[])])

    asyncio.run(client._fetch_and_store(channel))

    assert events == [
        "enter:read-session",
        "cursor:read-session",
        "exit:read-session",
    ]


def test_poll_loop_does_not_reset_engine_after_non_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_fake_client(monkeypatch)
    client._channel = object()
    client._closed_sequence = [False, True]
    reset_calls: list[str] = []

    class FakeDateTime:
        @staticmethod
        def now(_tz) -> datetime:
            return datetime(2026, 3, 30, 10, 0, tzinfo=UTC)

    async def fake_fetch_and_store(_channel: object) -> None:
        raise RuntimeError("parse failure")

    async def fake_reset_engine() -> None:
        reset_calls.append("reset")

    async def fake_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr(main_module, "datetime", FakeDateTime)
    monkeypatch.setattr(client, "_fetch_and_store", fake_fetch_and_store)
    monkeypatch.setattr(main_module, "is_disconnect_error", lambda _exc: False, raising=False)
    monkeypatch.setattr(main_module, "reset_engine", fake_reset_engine, raising=False)
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    asyncio.run(client._poll_loop())

    assert reset_calls == []
