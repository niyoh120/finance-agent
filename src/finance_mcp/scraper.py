import asyncio
import logging
import os
from datetime import timezone
from pathlib import Path

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
    def __init__(self, channel_id: int, db_path: Path, poll_interval: int = 300):
        super().__init__()
        self.channel_id = channel_id
        self.db_path = db_path
        self.poll_interval = poll_interval
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

        logger.info(f"Starting polling on #{channel.name}")

        while not self.is_closed():
            try:
                await self._fetch_and_store(channel)
            except Exception as e:
                logger.error(f"Polling error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _fetch_and_store(self, channel):
        async with self._session_maker() as session:
            last_id = await self._get_last_message_id(session)
            after = discord.Object(id=int(last_id)) if last_id else None

            count = 0
            async for message in channel.history(limit=100, after=after, oldest_first=True):
                data = parse_message(
                    message_id=str(message.id),
                    content=message.content,
                    timestamp=message.created_at.replace(tzinfo=timezone.utc),
                )

                if data:
                    await self._insert_flow(session, data)
                    count += 1

            if count > 0:
                await session.commit()
                logger.info(f"Inserted {count} new options flow records")

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

    if not token or not channel_id:
        logger.error("DISCORD_TOKEN and DISCORD_CHANNEL_ID are required")
        return

    client = OptionsFlowScraper(
        channel_id=int(channel_id),
        db_path=db_path,
        poll_interval=poll_interval,
    )
    client.run(token)


if __name__ == "__main__":
    main()
