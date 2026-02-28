from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import structlog
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.utils.message import get_text_from_message

from ..config import DiscordBotConfig
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
    def __init__(self, team: Team, config: DiscordBotConfig):
        self._team = team
        self._config = config
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    async def run_message(self, message: discord.Message) -> None:
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
            try:
                session_id = self._build_session_id(message)
                media = await self._prepare_media(message)
                self._team.additional_context = self._build_additional_context(message)

                stream = self._team.arun(  # type: ignore[misc]
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
                async with asyncio.timeout(max(5, self._config.run_timeout_seconds)):
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
                await self._cancel_run_if_needed(run_id)
                logger.warning("discord team run timeout", run_id=run_id)
                await editor.fail("请求处理超时，请稍后重试。")
            except asyncio.CancelledError:
                await self._cancel_run_if_needed(run_id)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "discord team run failed", error=str(exc), run_id=run_id
                )
                await editor.fail("处理消息时出现错误，请稍后重试。")

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

    async def _cancel_run_if_needed(self, run_id: str | None) -> None:
        if not run_id:
            return

        cancel_result = self._team.cancel_run(run_id)
        if inspect.isawaitable(cancel_result):
            await cancel_result

    @staticmethod
    def _build_session_id(message: discord.Message) -> str:
        guild_id = str(message.guild.id) if message.guild else "dm"
        return f"{guild_id}:{message.channel.id}"

    @staticmethod
    def _build_additional_context(message: discord.Message) -> str:
        return dedent(
            f"""
            Discord username: {message.author.name}
            Discord userid: {message.author.id}
            Discord url: {message.jump_url}
            Discord channel: {message.channel.id}
            """
        ).strip()


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
