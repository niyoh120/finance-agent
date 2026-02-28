from __future__ import annotations

import time

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError(
        "`discord.py` not installed. Please install using `pip install discord.py`"
    ) from exc


DISCORD_MESSAGE_LIMIT = 2000


class StreamMessageEditor:
    def __init__(
        self,
        message: discord.Message,
        *,
        min_edit_interval_ms: int,
        min_edit_chars: int,
        max_stream_chars: int,
    ):
        self._message = message
        self._min_edit_interval_sec = max(min_edit_interval_ms, 100) / 1000
        self._min_edit_chars = max(min_edit_chars, 1)
        self._max_stream_chars = min(max_stream_chars, DISCORD_MESSAGE_LIMIT - 10)

        self._full_text = ""
        self._last_sent_text = ""
        self._last_flush_at = 0.0
        self._chars_since_flush = 0

    @property
    def full_text(self) -> str:
        return self._full_text

    async def append(self, delta: str) -> None:
        if not delta:
            return

        self._full_text += delta
        self._chars_since_flush += len(delta)

        now = time.monotonic()
        due_to_time = now - self._last_flush_at >= self._min_edit_interval_sec
        due_to_size = self._chars_since_flush >= self._min_edit_chars

        if due_to_time and due_to_size:
            await self.flush()

    async def flush(self, force: bool = False) -> None:
        content = self._render_stream_content()
        if not force and content == self._last_sent_text:
            return

        await self._message.edit(content=content)
        self._last_sent_text = content
        self._last_flush_at = time.monotonic()
        self._chars_since_flush = 0

    async def finish(
        self,
        *,
        overflow_strategy: str,
        max_final_chars: int,
    ) -> None:
        final_text = self._full_text.strip()
        if not final_text:
            final_text = "（无输出）"

        safe_max_final_chars = min(max(max_final_chars, 100), DISCORD_MESSAGE_LIMIT)
        if len(final_text) <= safe_max_final_chars:
            await self._message.edit(content=final_text)
            return

        if overflow_strategy == "truncate":
            suffix = "\n\n...(已截断)"
            keep = max(1, safe_max_final_chars - len(suffix))
            await self._message.edit(content=f"{final_text[:keep]}{suffix}")
            return

        chunks = _split_text(final_text, safe_max_final_chars)
        total = len(chunks)
        await self._message.edit(content=f"[1/{total}] {chunks[0]}")

        for index, chunk in enumerate(chunks[1:], start=2):
            await self._message.channel.send(f"[{index}/{total}] {chunk}")

    async def fail(self, error_message: str) -> None:
        await self._message.edit(content=error_message)

    def _render_stream_content(self) -> str:
        if not self._full_text.strip():
            return "正在分析中..."

        if len(self._full_text) <= self._max_stream_chars:
            return self._full_text

        tail = self._full_text[-self._max_stream_chars :]
        return f"...\n{tail}"


def _split_text(text: str, chunk_size: int) -> list[str]:
    if chunk_size <= 0:
        return [text]

    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
