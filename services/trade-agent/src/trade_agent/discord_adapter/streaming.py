from __future__ import annotations

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError("`discord.py` not installed. Please install using `pip install discord.py`") from exc

from .formatting import build_final_render, normalize_markdown, split_markdown_text
from .views import FullTextView

DISCORD_MESSAGE_LIMIT = 2000


class StreamMessageEditor:
    def __init__(
        self,
        source_message: discord.Message,
        *,
        min_edit_interval_ms: int,
        min_edit_chars: int,
        max_stream_chars: int,
        render_mode: str,
        buttons_enabled: bool,
        button_full_text_max_chars: int,
    ):
        self._source_message = source_message
        self._message: discord.Message | None = None
        _ = min_edit_interval_ms, min_edit_chars, max_stream_chars
        self._render_mode = render_mode
        self._buttons_enabled = buttons_enabled
        self._button_full_text_max_chars = max(1000, button_full_text_max_chars)

        self._full_text = ""
        self._allowed_mentions = discord.AllowedMentions.none()

    @property
    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text

    async def finish(
        self,
        *,
        overflow_strategy: str,
        max_final_chars: int,
    ) -> None:
        final_text = normalize_markdown(self._full_text.strip())
        if not final_text:
            final_text = "（无输出）"

        safe_max_final_chars = min(max(max_final_chars, 100), DISCORD_MESSAGE_LIMIT)
        if len(final_text) <= safe_max_final_chars:
            render = build_final_render(final_text, self._render_mode)
            await self._upsert(content=render.content, embed=render.embed)
            return

        view = self._build_full_text_view(final_text)

        if overflow_strategy == "truncate":
            suffix = "\n\n...(已截断)"
            keep = max(1, safe_max_final_chars - len(suffix))
            truncated = normalize_markdown(f"{final_text[:keep]}{suffix}")
            render = build_final_render(truncated, self._render_mode)
            await self._upsert(content=render.content, embed=render.embed, view=view)
            return

        chunks = split_markdown_text(final_text, safe_max_final_chars)
        total = len(chunks)
        await self._upsert(content=f"[1/{total}] {chunks[0]}", view=view)

        for index, chunk in enumerate(chunks[1:], start=2):
            await self._source_message.channel.send(
                f"[{index}/{total}] {chunk}", allowed_mentions=self._allowed_mentions
            )

    async def fail(self, error_message: str) -> None:
        await self._upsert(content=error_message, embed=None, view=None)

    async def _upsert(
        self,
        *,
        content: str | None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
    ) -> None:
        if self._message is None:
            self._message = await self._source_message.reply(
                content=content,
                embed=embed,
                view=view,
                mention_author=False,
                allowed_mentions=self._allowed_mentions,
            )
            return

        await self._message.edit(
            content=content,
            embed=embed,
            view=view,
            allowed_mentions=self._allowed_mentions,
        )

    def _build_full_text_view(self, full_text: str) -> discord.ui.View | None:
        if not self._buttons_enabled:
            return None

        return FullTextView(
            full_text=full_text,
            requester_id=self._source_message.author.id,
            max_text_chars=self._button_full_text_max_chars,
        )
