import asyncio
import json
import logging
import os
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .models import DATABASE_PATH, OptionsFlow, create_engine, create_session_maker, init_db
from .parser import parse_message

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class OptionsFlowScraper(discord.Client):
    def __init__(
        self,
        channel_id: int,
        db_path: Path,
        poll_interval: int = 300,
        start_date: datetime | None = None,
    ):
        super().__init__()
        self.channel_id = channel_id
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.start_date = start_date
        self._polling_task: asyncio.Task | None = None
        self._engine = None
        self._session_maker = None

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        await init_db(self.db_path)
        self._engine = create_engine(self.db_path)
        self._session_maker = create_session_maker(self._engine)
        self._polling_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self):
        await self.wait_until_ready()
        channel = self.get_channel(self.channel_id)

        if not channel:
            logger.error(f"Channel {self.channel_id} not found")
            return

        channel_name = getattr(channel, "name", "unknown_channel")
        logger.info(f"Starting polling on #{channel_name} (ID: {self.channel_id})")

        tz_et = ZoneInfo("America/New_York")
        market_open = time(9, 30)
        market_close = time(16, 15)

        while not self.is_closed():
            now_et = datetime.now(tz_et)

            if now_et.weekday() >= 5:
                logger.debug("Weekend, skipping poll.")
            else:
                current_time = now_et.time()
                is_trading_time = market_open <= current_time <= market_close

                if not is_trading_time:
                    logger.debug(f"Outside trading hours ({current_time} ET), skipping poll.")
                else:
                    try:
                        logger.debug("Polling for new messages...")
                        await self._fetch_and_store(channel)
                    except Exception as e:
                        logger.error(f"Polling error: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    async def _fetch_and_store(self, channel):
        if not self._session_maker:
            logger.error("Database session maker not initialized")
            return

        async with self._session_maker() as session:
            last_id = await self._get_last_message_id(session)

            if last_id:
                after = discord.Object(id=int(last_id))
                logger.info(f"Fetching messages after ID {last_id}")
            else:
                start_date = self.start_date or datetime(2025, 12, 1, tzinfo=timezone.utc)
                after = discord.Object(id=discord.utils.time_snowflake(start_date))
                logger.info(
                    f"Fetching initial batch of messages starting from {start_date} (ID: {after.id})"
                )

            count = 0
            total_fetched = 0
            async for message in channel.history(limit=100, after=after, oldest_first=True):
                total_fetched += 1

                if message.author.name != "UW Live Options Flow":
                    logger.debug(f"Skipping message from {message.author.name} (ID: {message.id})")
                    continue

                content = message.content
                if not content and message.embeds:
                    embed = message.embeds[0]
                    parts = []
                    if embed.title:
                        parts.append(embed.title)
                    if embed.description:
                        parts.append(embed.description)
                    for field in embed.fields:
                        parts.append(f"{field.name}: {field.value}")

                    content = "\n".join(parts)

                data = parse_message(
                    message_id=str(message.id),
                    content=content,
                    timestamp=message.created_at.replace(tzinfo=timezone.utc),
                )

                if data:
                    await self._insert_flow(session, data)
                    count += 1
                else:
                    if total_fetched <= 5:
                        log_content = content[:200] if content else "<empty>"
                        logger.warning(f"Failed to parse message {message.id}: {log_content!r}")
                        if not message.content and message.embeds:
                            logger.warning(f"Reconstructed content: {content!r}")
                            try:
                                embed_dict = message.embeds[0].to_dict()
                                logger.warning(
                                    f"Embed structure: {json.dumps(embed_dict, default=str)}"
                                )
                            except Exception:
                                pass
                    else:
                        logger.debug(f"Failed to parse message {message.id}")

            logger.info(f"Processed {total_fetched} messages, inserted {count} new records")

            if count > 0:
                await session.commit()
                logger.info(f"Committed {count} records to database")

    async def _get_last_message_id(self, session) -> str | None:
        result = await session.execute(
            select(OptionsFlow.message_id).order_by(OptionsFlow.id.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        return row

    async def _insert_flow(self, session, data):
        stmt = (
            insert(OptionsFlow)
            .values(
                message_id=data.message_id,
                timestamp=data.timestamp,
                interval_type=data.interval_type,
                side=data.side,
                symbol=data.symbol,
                strike=data.strike,
                option_type=data.option_type,
                expiry=data.expiry,
                dte=data.dte,
                interval_volume=data.interval_volume,
                open_interest=data.open_interest,
                vol_oi=data.vol_oi,
                otm_percent=data.otm_percent,
                bid_percent=data.bid_percent,
                ask_percent=data.ask_percent,
                premium=data.premium,
                avg_fill=data.avg_fill,
                multileg_percent=data.multileg_percent,
                raw_message=data.raw_message,
            )
            .on_conflict_do_nothing(index_elements=["message_id"])
        )

        await session.execute(stmt)


def main():
    token = os.getenv("DISCORD_TOKEN")
    channel_id = os.getenv("DISCORD_CHANNEL_ID")
    db_path = Path(os.getenv("DATABASE_PATH", DATABASE_PATH))
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    start_date_str = os.getenv("FETCH_START_DATE")
    start_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(f"Invalid FETCH_START_DATE format: {start_date_str}. Using default.")

    if not start_date:
        start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)

    if not token or not channel_id:
        logger.error("DISCORD_TOKEN and DISCORD_CHANNEL_ID are required")
        return

    client = OptionsFlowScraper(
        channel_id=int(channel_id),
        db_path=db_path,
        poll_interval=poll_interval,
        start_date=start_date,
    )
    client.run(token)


if __name__ == "__main__":
    main()
