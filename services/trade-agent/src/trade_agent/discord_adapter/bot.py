from __future__ import annotations

import asyncio
from os import getenv
from typing import Callable

import structlog
from agno.team.team import Team
import discord

from ..config import DiscordBotConfig
from .filtering import should_process_message
from .runner import TeamRunRunner

logger = structlog.get_logger(__name__)


class TradeDiscordBot(discord.Client):
    def __init__(self, team_factory: Callable[[], Team], config: DiscordBotConfig):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        super().__init__(intents=intents)
        self._runner = TeamRunRunner(team_factory=team_factory, config=config)
        self._tasks: set[asyncio.Task[None]] = set()

    async def on_ready(self) -> None:
        logger.info("discord bot ready", user=str(self.user))

    async def on_message(self, message: discord.Message) -> None:
        bot_user_id = self.user.id if self.user else None
        if not should_process_message(message, bot_user_id):
            return

        task = asyncio.create_task(self._runner.run_message(message, bot_user_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        await super().close()

    def serve(self) -> None:
        token = getenv("FA_DISCORD_BOT_TOKEN")
        if not token:
            raise ValueError("FA_DISCORD_BOT_TOKEN NOT SET")
        self.run(token)
