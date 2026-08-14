import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from shared.database import safe_session_scope
from shared.logging import configure_logging
from shared.models.options import OptionsFlow
from shared.options_flow_parser import OptionsFlowData, parse_message
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

configure_logging(service="options-scraper")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    discord_token: str
    channel_id: int
    poll_interval: int
    start_date: datetime


def load_settings() -> Settings:
    discord_token = os.getenv("FA_OPTIONS_SCRAPER_DISCORD_TOKEN")
    channel_id_raw = os.getenv("FA_OPTIONS_SCRAPER_CHANNEL_ID")
    poll_interval = int(os.getenv("FA_OPTIONS_SCRAPER_POLL_INTERVAL", "300"))
    start_date_raw = os.getenv("FA_OPTIONS_SCRAPER_START_DATE", "2025-12-01")

    if not discord_token:
        raise ValueError("FA_OPTIONS_SCRAPER_DISCORD_TOKEN is required")
    if not channel_id_raw:
        raise ValueError("FA_OPTIONS_SCRAPER_CHANNEL_ID is required")

    start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").replace(tzinfo=UTC)

    return Settings(
        discord_token=discord_token,
        channel_id=int(channel_id_raw),
        poll_interval=poll_interval,
        start_date=start_date,
    )


def build_message_content(message: object) -> str:
    content = getattr(message, "content", "")
    if content:
        return str(content)

    embeds = getattr(message, "embeds", [])
    if not embeds:
        return ""

    embed = embeds[0]
    parts: list[str] = []
    title = getattr(embed, "title", None)
    description = getattr(embed, "description", None)
    fields = getattr(embed, "fields", [])

    if title:
        parts.append(str(title))
    if description:
        parts.append(str(description))
    for field in fields:
        parts.append(f"{field.name}: {field.value}")

    return "\n".join(parts)


class OptionsFlowScraper:
    def __init__(self, settings: Settings):
        self.settings = settings


def build_flow_values(data: OptionsFlowData) -> dict[str, object]:
    """Map a parsed flow to the OptionsFlow insert row (all columns except id/created_at)."""
    return {
        "message_id": data.message_id,
        "timestamp": data.timestamp,
        "interval_type": data.interval_type,
        "side": data.side,
        "symbol": data.symbol,
        "strike": data.strike,
        "option_type": data.option_type,
        "expiry": data.expiry,
        "dte": data.dte,
        "interval_volume": data.interval_volume,
        "open_interest": data.open_interest,
        "vol_oi": data.vol_oi,
        "otm_percent": data.otm_percent,
        "bid_percent": data.bid_percent,
        "ask_percent": data.ask_percent,
        "premium": data.premium,
        "avg_fill": data.avg_fill,
        "multileg_percent": data.multileg_percent,
        "raw_message": data.raw_message,
    }


def get_resume_cursor(
    message_rows: list[tuple[str, datetime]],
    time_snowflake: Callable[[datetime], int],
) -> int | None:
    if not message_rows:
        return None

    latest_timestamp = max(timestamp for _, timestamp in message_rows)
    numeric_ids = [
        int(message_id)
        for message_id, timestamp in message_rows
        if timestamp == latest_timestamp and message_id.isdigit()
    ]
    if numeric_ids:
        return max(numeric_ids)
    return int(time_snowflake(latest_timestamp))


def build_discord_client(settings: Settings):  # pragma: no cover - exercised via runtime smoke test
    import discord

    class OptionsFlowDiscordClient(discord.Client):
        def __init__(self, client_settings: Settings, **kwargs: object):
            super().__init__(**kwargs)
            self._settings = client_settings
            self._polling_task: asyncio.Task[None] | None = None

        async def on_ready(self) -> None:
            logger.info("Logged in as %s", self.user)
            # discord.py re-fires on_ready on every reconnect/resume; without this
            # guard each reconnect would spawn an extra polling loop.
            if self._polling_task is not None and not self._polling_task.done():
                return
            self._polling_task = asyncio.create_task(self._poll_loop())

        async def _poll_loop(self) -> None:
            await self.wait_until_ready()
            channel = self.get_channel(self._settings.channel_id)
            if channel is None:
                logger.error("Channel %s not found", self._settings.channel_id)
                return

            timezone_et = ZoneInfo("America/New_York")
            market_open = time(9, 30)
            market_close = time(16, 15)

            while not self.is_closed():
                now_et = datetime.now(timezone_et)
                if now_et.weekday() < 5 and market_open <= now_et.time() <= market_close:
                    try:
                        await self._fetch_and_store(channel)
                    except Exception:
                        # 断连重置由 safe_session_scope 内部处理，这里只保证循环存活。
                        logger.exception("Polling error")
                await asyncio.sleep(self._settings.poll_interval)

        async def _fetch_and_store(self, channel: object) -> None:
            resume_cursor = await self._get_resume_cursor_from_db(discord.utils.time_snowflake)
            if resume_cursor is not None:
                after = discord.Object(id=resume_cursor)
            else:
                after = discord.Object(id=discord.utils.time_snowflake(self._settings.start_date))

            parsed_flows = await self._collect_parsed_flows(channel, after)
            inserted = await self._store_flows(parsed_flows)

            if inserted:
                logger.info("Inserted %s options flow rows", inserted)

        async def _get_resume_cursor_from_db(self, time_snowflake: Callable[[datetime], int]) -> int | None:
            async with safe_session_scope() as session:
                return await self._get_resume_cursor(session, time_snowflake)

        async def _collect_parsed_flows(self, channel: object, after: object) -> list[OptionsFlowData]:
            parsed_flows: list[OptionsFlowData] = []
            async for message in channel.history(limit=100, after=after, oldest_first=True):
                author_name = getattr(getattr(message, "author", None), "name", "")
                if author_name != "UW Live Options Flow":
                    continue
                content = build_message_content(message)
                parsed = parse_message(str(message.id), content, message.created_at.astimezone(UTC))
                if parsed is None:
                    continue
                parsed_flows.append(parsed)
            return parsed_flows

        async def _store_flows(self, parsed_flows: list[OptionsFlowData]) -> int:
            if not parsed_flows:
                return 0

            stmt = (
                insert(OptionsFlow)
                .values([build_flow_values(parsed_flow) for parsed_flow in parsed_flows])
                .on_conflict_do_nothing(index_elements=["message_id"])
            )
            async with safe_session_scope() as session:
                result = await session.execute(stmt)
            # rowcount 只统计实际插入的行，on_conflict 跳过的行不计入日志。
            return result.rowcount or 0

        async def _get_resume_cursor(self, session: object, time_snowflake: Callable[[datetime], int]) -> int | None:
            result = await session.execute(
                select(OptionsFlow.message_id, OptionsFlow.timestamp)
                .order_by(OptionsFlow.timestamp.desc(), OptionsFlow.id.desc())
                .limit(100)
            )
            message_rows = [(message_id, timestamp) for message_id, timestamp in result.all()]
            return get_resume_cursor(message_rows, time_snowflake)

    return OptionsFlowDiscordClient(settings)


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as exc:
        logger.error(str(exc))
        return

    build_discord_client(settings).run(settings.discord_token)


if __name__ == "__main__":
    main()
