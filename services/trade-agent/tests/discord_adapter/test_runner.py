from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from trade_agent.config import DiscordBotConfig
from trade_agent.discord_adapter.runner import TeamRunRunner


class _FakeTyping:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> None:
        self.entered += 1

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited += 1


class _FakeSentMessage:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, object]] = []

    async def edit(self, **kwargs) -> None:
        self.edit_calls.append(kwargs)


class _FakeChannel:
    def __init__(self) -> None:
        self.typing_ctx = _FakeTyping()
        self.sent_messages: list[dict[str, object]] = []
        self.id = 456

    def typing(self) -> _FakeTyping:
        return self.typing_ctx

    async def send(self, content: str, **kwargs) -> None:
        self.sent_messages.append({"content": content, **kwargs})


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.channel = _FakeChannel()
        self.author = SimpleNamespace(id=123, name="alice", display_name="Alice", bot=False)
        self.guild = SimpleNamespace(id=789)
        self.attachments = []
        self.jump_url = "https://discord.test/message/1"
        self.reply_calls: list[dict[str, object]] = []
        self.sent_message = _FakeSentMessage()

    async def reply(self, **kwargs):
        self.reply_calls.append(kwargs)
        return self.sent_message


class _FakeTeam:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.additional_context = ""
        self.arun_calls: list[dict[str, object]] = []
        self.cancelled_run_ids: list[str] = []

    def get_session(self, session_id: str):
        return None

    def arun(self, **kwargs):
        self.arun_calls.append(kwargs)

        async def _stream():
            for event in self.events:
                yield event

        return _stream()

    def cancel_run(self, run_id: str) -> None:
        self.cancelled_run_ids.append(run_id)


class TeamRunRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_events_only_create_single_final_reply(self) -> None:
        events = [
            SimpleNamespace(content="第一段", run_id="run-1"),
            SimpleNamespace(content="第一段\n\n- 第二段", run_id="run-1"),
        ]
        team = _FakeTeam(events)
        runner = TeamRunRunner(lambda: team, DiscordBotConfig(min_edit_chars=1, render_mode="markdown"))
        message = _FakeMessage("分析一下 TSLA")

        await runner.run_message(message, bot_user_id=999)

        self.assertEqual(len(team.arun_calls), 1)
        self.assertTrue(team.arun_calls[0]["stream"])
        self.assertEqual(message.channel.typing_ctx.entered, 1)
        self.assertEqual(message.channel.typing_ctx.exited, 1)
        self.assertEqual(len(message.reply_calls), 1)
        self.assertEqual(message.sent_message.edit_calls, [])
        self.assertEqual(message.reply_calls[0]["content"], "第一段\n\n- 第二段")

    async def test_additional_context_includes_discord_formatting_guidance(self) -> None:
        runner = TeamRunRunner(lambda: _FakeTeam([]), DiscordBotConfig())
        message = _FakeMessage("你好")

        context = runner._build_additional_context(message, history_context="")

        self.assertIn("Discord 回复格式要求", context)
        self.assertIn("先给结论", context)
        self.assertIn("使用简短小标题和项目符号", context)

    async def test_stream_events_ignore_non_team_content_events(self) -> None:
        events = [
            SimpleNamespace(event="TeamToolCallStarted", content="不应展示", run_id="run-1"),
            SimpleNamespace(event="RunContent", content="成员中间输出", run_id="run-1"),
            SimpleNamespace(event="TeamRunContent", content="最终答案", run_id="run-1"),
        ]
        team = _FakeTeam(events)
        runner = TeamRunRunner(
            lambda: team,
            DiscordBotConfig(min_edit_chars=1, render_mode="markdown", stream_events=True, stream_member_events=True),
        )
        message = _FakeMessage("分析一下 NVDA")

        await runner.run_message(message, bot_user_id=999)

        self.assertEqual(message.reply_calls[0]["content"], "最终答案")
