from __future__ import annotations

import unittest
from types import SimpleNamespace

from trade_agent.discord_adapter.streaming import StreamMessageEditor


class _FakeSentMessage:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, object]] = []

    async def edit(self, **kwargs) -> None:
        self.edit_calls.append(kwargs)


class _FakeChannel:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send(self, content: str, **kwargs) -> None:
        self.sent_messages.append({"content": content, **kwargs})


class _FakeSourceMessage:
    def __init__(self) -> None:
        self.author = SimpleNamespace(id=123)
        self.channel = _FakeChannel()
        self.reply_calls: list[dict[str, object]] = []
        self.sent_message = _FakeSentMessage()

    async def reply(self, **kwargs):
        self.reply_calls.append(kwargs)
        return self.sent_message


class StreamMessageEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_finish_uses_full_text_without_intermediate_edit(self) -> None:
        source_message = _FakeSourceMessage()
        editor = StreamMessageEditor(
            source_message,
            min_edit_interval_ms=700,
            min_edit_chars=24,
            max_stream_chars=1800,
            render_mode="markdown",
            buttons_enabled=True,
            button_full_text_max_chars=10000,
        )

        editor.set_full_text("最终结论\n\n- 要点 1")  # type: ignore[attr-defined]
        await editor.finish(overflow_strategy="split", max_final_chars=1900)

        self.assertEqual(len(source_message.reply_calls), 1)
        self.assertEqual(source_message.sent_message.edit_calls, [])
        self.assertEqual(source_message.reply_calls[0]["content"], "最终结论\n\n- 要点 1")
