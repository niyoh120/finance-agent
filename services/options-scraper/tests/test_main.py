import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import options_scraper.main as main_module
import pytest
from options_scraper.main import (
    Settings,
    build_discord_client,
    build_message_content,
    get_resume_cursor,
    load_settings,
)
from shared.options_flow_parser import parse_message


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


SAMPLE_FLOW_CONTENT = """🕑 Interval (5 Min) - Bid Side
**[MSTR 145 P 04/17/2026 (92 DTE)](https://example.com)**
Interval Volume: 1,234
Open Interest: 432
Vol/OI: 2.86
OTM: 10%
Bid/Ask %: 70/30
Premium: $123,000
Average Fill: $4.56
Multi-leg Volume: 12.5%
"""


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

    class FakeResult:
        rowcount = 1

    @asynccontextmanager
    async def fake_safe_session_scope():
        session_name = next(session_names)
        events.append(f"enter:{session_name}")

        class FakeSession:
            async def execute(self, _stmt: object) -> FakeResult:
                events.append(f"execute:{session_name}")
                return FakeResult()

        try:
            yield FakeSession()
        finally:
            events.append(f"exit:{session_name}")

    async def fake_get_resume_cursor(session: object, _time_snowflake) -> int | None:
        events.append(f"cursor:{session.__class__.__name__}")
        return None

    monkeypatch.setattr(main_module, "safe_session_scope", fake_safe_session_scope)
    monkeypatch.setattr(client, "_get_resume_cursor", fake_get_resume_cursor)
    monkeypatch.setattr(
        main_module,
        "parse_message",
        lambda *_args: parse_message("123", SAMPLE_FLOW_CONTENT, datetime(2026, 1, 5, tzinfo=UTC)),
    )

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
        "cursor:FakeSession",
        "exit:read-session",
        "history:start",
        "enter:write-session",
        "execute:write-session",
        "exit:write-session",
    ]


def test_store_flows_batch_inserts_and_reports_rowcount(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_fake_client(monkeypatch)
    executed: list[object] = []

    class FakeResult:
        rowcount = 2

    @asynccontextmanager
    async def fake_safe_session_scope():
        class FakeSession:
            async def execute(self, stmt: object) -> FakeResult:
                executed.append(stmt)
                return FakeResult()

        yield FakeSession()

    monkeypatch.setattr(main_module, "safe_session_scope", fake_safe_session_scope)

    parsed = [parse_message(str(i), SAMPLE_FLOW_CONTENT, datetime(2026, 1, 5, tzinfo=UTC)) for i in range(3)]

    inserted = asyncio.run(client._store_flows(parsed))

    # 3 rows go out in ONE batch statement; rowcount (not len) is reported.
    assert len(executed) == 1
    assert inserted == 2


def test_build_flow_values_maps_all_columns() -> None:
    sample = """🔥 Hot Contract - Ask Side
**[TSLA 300 C 05/16/2026 (20 DTE)](https://example.com)**
Overall Volume: 5,678
Open Interest: 120
Vol/OI: 47.3
OTM: 3.5%
Bid/Ask %: 25/75
Premium: $980,000
Average Fill: $12.34
Multi-leg Volume: 0%
"""
    parsed = parse_message("456", sample, datetime(2026, 4, 26, tzinfo=UTC))
    assert parsed is not None

    values = main_module.build_flow_values(parsed)

    assert values["message_id"] == "456"
    assert values["timestamp"] == parsed.timestamp
    assert values["symbol"] == "TSLA"
    assert values["raw_message"] == sample
    assert set(values) == {
        "message_id",
        "timestamp",
        "interval_type",
        "side",
        "symbol",
        "strike",
        "option_type",
        "expiry",
        "dte",
        "interval_volume",
        "open_interest",
        "vol_oi",
        "otm_percent",
        "bid_percent",
        "ask_percent",
        "premium",
        "avg_fill",
        "multileg_percent",
        "raw_message",
    }


def test_fetch_and_store_skips_write_session_when_nothing_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_fake_client(monkeypatch)
    events: list[str] = []

    @asynccontextmanager
    async def fake_safe_session_scope():
        events.append("enter:read-session")
        try:
            yield "read-session"
        finally:
            events.append("exit:read-session")

    async def fake_get_resume_cursor(session: object, _time_snowflake) -> int | None:
        events.append(f"cursor:{session}")
        return None

    monkeypatch.setattr(main_module, "safe_session_scope", fake_safe_session_scope)
    monkeypatch.setattr(client, "_get_resume_cursor", fake_get_resume_cursor)
    monkeypatch.setattr(main_module, "parse_message", lambda *_args: None)

    channel = DummyChannel([DummyMessage(content="flow", embeds=[])])

    asyncio.run(client._fetch_and_store(channel))

    assert events == [
        "enter:read-session",
        "cursor:read-session",
        "exit:read-session",
    ]


def test_poll_loop_survives_fetch_and_store_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询循环遇到任意异常（含 DB 断连）都必须存活；断连重置由 safe_session_scope 负责。"""
    client = build_fake_client(monkeypatch)
    client._channel = object()
    client._closed_sequence = [False, False, True]
    attempts: list[str] = []

    class FakeDateTime:
        @staticmethod
        def now(_tz) -> datetime:
            return datetime(2026, 3, 30, 10, 0, tzinfo=UTC)

    async def fake_fetch_and_store(_channel: object) -> None:
        attempts.append("attempt")
        raise RuntimeError("disconnect or parse failure")

    async def fake_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr(main_module, "datetime", FakeDateTime)
    monkeypatch.setattr(client, "_fetch_and_store", fake_fetch_and_store)
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    asyncio.run(client._poll_loop())

    assert attempts == ["attempt", "attempt"]


def test_on_ready_does_not_spawn_duplicate_poll_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    """discord.py 重连时会再次触发 on_ready；重复触发必须复用存活的轮询任务。"""
    client = build_fake_client(monkeypatch)
    started: list[str] = []

    async def blocking_poll_loop() -> None:
        started.append("started")
        await asyncio.sleep(3600)

    async def fake_wait_until_ready() -> None:
        return None

    monkeypatch.setattr(client, "_poll_loop", blocking_poll_loop)
    monkeypatch.setattr(client, "wait_until_ready", fake_wait_until_ready)

    async def scenario() -> None:
        client.user = "fake-bot"
        await client.on_ready()
        # 让出控制权，轮询任务真正开始运行。
        await asyncio.sleep(0)
        first_task = client._polling_task
        assert first_task is not None
        # 模拟断线重连后 on_ready 再次触发。
        await client.on_ready()
        assert client._polling_task is first_task
        first_task.cancel()

    asyncio.run(scenario())

    assert started == ["started"]
