from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from textwrap import dedent
from typing import Any
from typing import Callable

import structlog
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.utils.message import get_text_from_message

from ..config import DiscordBotConfig
from .filtering import ALLOWED_MESSAGE_TYPES
from .streaming import StreamMessageEditor

try:
    import discord
except (ImportError, ModuleNotFoundError) as exc:
    raise ImportError(
        "`discord.py` not installed. Please install using `pip install discord.py`"
    ) from exc

logger = structlog.get_logger(__name__)


@dataclass
class PreparedMedia:
    images: list[Image] | None = None
    videos: list[Video] | None = None
    audio: list[Audio] | None = None
    files: list[File] | None = None


class TeamRunRunner:
    def __init__(self, team_factory: Callable[[], Team], config: DiscordBotConfig):
        self._team_factory = team_factory
        self._config = config
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrency))
        self._thread_locks: dict[int, asyncio.Lock] = {}

    async def run_message(
        self, message: discord.Message, bot_user_id: int | None
    ) -> None:
        thread_lock = self._get_thread_lock(message.channel.id)
        async with thread_lock:
            async with self._semaphore:
                placeholder = await message.reply(
                    self._config.placeholder_text, mention_author=False
                )
                editor = StreamMessageEditor(
                    placeholder,
                    min_edit_interval_ms=self._config.min_edit_interval_ms,
                    min_edit_chars=self._config.min_edit_chars,
                    max_stream_chars=self._config.max_stream_chars,
                )

                run_id: str | None = None
                team = self._team_factory()
                try:
                    session_id = self._build_session_id(message)
                    media = await self._prepare_media(message)
                    history_context = await self._build_thread_history_context(
                        message, bot_user_id
                    )
                    team.additional_context = self._build_additional_context(
                        message, history_context
                    )

                    stream = team.arun(  # type: ignore[misc]
                        input=message.content or "",
                        user_id=str(message.author.id),
                        session_id=session_id,
                        images=media.images,
                        videos=media.videos,
                        audio=media.audio,
                        files=media.files,
                        stream=True,
                        stream_events=self._config.stream_events,
                        stream_member_events=self._config.stream_member_events,
                    )

                    last_seen_text = ""
                    async with asyncio.timeout(
                        max(5, self._config.run_timeout_seconds)
                    ):
                        async for event in stream:
                            event_run_id = getattr(event, "run_id", None)
                            if isinstance(event_run_id, str) and event_run_id:
                                run_id = event_run_id

                            text = _extract_text(event)
                            if not text:
                                continue

                            delta, last_seen_text = _as_delta(text, last_seen_text)
                            await editor.append(delta)

                    await editor.flush(force=True)
                    await editor.finish(
                        overflow_strategy=self._config.final_overflow_strategy,
                        max_final_chars=self._config.max_final_chars,
                    )
                except asyncio.TimeoutError:
                    await self._cancel_run_if_needed(team, run_id)
                    logger.warning("discord team run timeout", run_id=run_id)
                    await editor.fail("请求处理超时，请稍后重试。")
                except asyncio.CancelledError:
                    await self._cancel_run_if_needed(team, run_id)
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "discord team run failed", error=str(exc), run_id=run_id
                    )
                    await editor.fail("处理消息时出现错误，请稍后重试。")

    def _get_thread_lock(self, thread_id: int) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock

        return lock

    async def _prepare_media(self, message: discord.Message) -> PreparedMedia:
        if not message.attachments:
            return PreparedMedia()

        images: list[Image] = []
        videos: list[Video] = []
        audio: list[Audio] = []
        files: list[File] = []

        for attachment in message.attachments:
            content_type = attachment.content_type or ""

            if content_type.startswith("image/"):
                images.append(Image(url=attachment.url))
                continue

            if content_type.startswith("audio/"):
                audio.append(Audio(url=attachment.url))
                continue

            if content_type.startswith("video/"):
                videos.append(Video(content=await attachment.read()))
                continue

            files.append(File(content=await attachment.read()))

        return PreparedMedia(
            images=images or None,
            videos=videos or None,
            audio=audio or None,
            files=files or None,
        )

    async def _cancel_run_if_needed(self, team: Team, run_id: str | None) -> None:
        if not run_id:
            return

        cancel_result = team.cancel_run(run_id)
        if inspect.isawaitable(cancel_result):
            await cancel_result

    @staticmethod
    def _build_session_id(message: discord.Message) -> str:
        if isinstance(message.channel, discord.Thread):
            guild_id = str(message.guild.id) if message.guild else "dm"
            return f"{guild_id}:thread:{message.channel.id}"

        guild_id = str(message.guild.id) if message.guild else "dm"
        return f"{guild_id}:channel:{message.channel.id}"

    def _build_additional_context(
        self, message: discord.Message, history_context: str
    ) -> str:
        context = dedent(
            f"""
            Discord username: {message.author.name}
            Discord userid: {message.author.id}
            Discord url: {message.jump_url}
            Discord channel: {message.channel.id}
            """
        ).strip()

        if isinstance(message.channel, discord.Thread):
            thread_context = dedent(
                f"""
                Discord thread id: {message.channel.id}
                Discord thread name: {message.channel.name}
                Discord parent channel: {message.channel.parent_id}
                """
            ).strip()
            context = f"{context}\n{thread_context}"

        if history_context:
            context = (
                f"{context}\n\n<discord_history>\n{history_context}\n</discord_history>"
            )

        return context

    async def _build_thread_history_context(
        self, message: discord.Message, bot_user_id: int | None
    ) -> str:
        channel = message.channel
        if not isinstance(channel, discord.Thread):
            return ""

        lines: list[str] = []
        try:
            async for item in channel.history(
                limit=max(1, self._config.thread_history_messages),
                before=message,
                oldest_first=True,
            ):
                if item.webhook_id is not None:
                    continue

                if item.type not in ALLOWED_MESSAGE_TYPES:
                    continue

                if item.author.bot:
                    if bot_user_id is not None and item.author.id == bot_user_id:
                        pass
                    elif not self._config.thread_history_include_bots:
                        continue

                text = (item.content or "").strip()
                attachment_summary = _format_attachments(item.attachments)
                if not text and not attachment_summary:
                    continue

                role = (
                    "assistant"
                    if bot_user_id is not None and item.author.id == bot_user_id
                    else "user"
                )
                timestamp = item.created_at.isoformat(timespec="seconds")
                line = f"[{timestamp}] [{role}] {item.author.display_name}: {text or '(no text)'}"
                if attachment_summary:
                    line = f"{line} {attachment_summary}"

                lines.append(line)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "discord thread history unavailable",
                channel_id=channel.id,
                error=str(exc),
            )
            return ""

        if not lines:
            return ""

        history = "\n".join(lines)
        max_chars = max(500, self._config.thread_history_max_chars)
        if len(history) > max_chars:
            history = f"...(history truncated)\n{history[-max_chars:]}"

        return history


def _format_attachments(attachments: list[discord.Attachment]) -> str:
    if not attachments:
        return ""

    formatted = []
    for attachment in attachments[:3]:
        content_type = attachment.content_type or "unknown"
        formatted.append(f"{attachment.filename} ({content_type})")

    extra = ""
    if len(attachments) > 3:
        extra = f" +{len(attachments) - 3} more"

    return f"[attachments: {', '.join(formatted)}{extra}]"


def _extract_text(event: Any) -> str:
    content = getattr(event, "content", None)
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    return get_text_from_message(content)


def _as_delta(current_text: str, previous_text: str) -> tuple[str, str]:
    if not previous_text:
        return current_text, current_text

    if current_text.startswith(previous_text):
        return current_text[len(previous_text) :], current_text

    return current_text, previous_text + current_text
