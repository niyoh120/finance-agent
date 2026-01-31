import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from shared.models import NewsArticle, OptionsFlow
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .options_parser import parse_message

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.bubbleseek.ai/api/events/public"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://bubbleseek.ai/",
    "Origin": "https://bubbleseek.ai",
}
BACKFILL_START_DATE = datetime(2025, 12, 1, tzinfo=timezone.utc)


class BubbleSeekScraper:
    async def get_latest_event_time(self, session: AsyncSession) -> Optional[datetime]:
        """Get the latest event time from both NewsArticle and OptionsFlow tables."""
        # Check NewsArticle table
        news_stmt = (
            select(NewsArticle.published_at)
            .order_by(desc(NewsArticle.published_at))
            .limit(1)
        )
        news_result = await session.execute(news_stmt)
        latest_news = news_result.scalar_one_or_none()

        # Check OptionsFlow table
        options_stmt = (
            select(OptionsFlow.timestamp).order_by(desc(OptionsFlow.timestamp)).limit(1)
        )
        options_result = await session.execute(options_stmt)
        latest_options = options_result.scalar_one_or_none()

        # Only skip backfill if BOTH tables have data
        # If either table is empty, return None to trigger backfill
        if latest_news is None or latest_options is None:
            return None
        # Both have data, return the older one to avoid gaps
        return min(latest_news, latest_options)

    async def fetch_events_page(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        url = f"{API_BASE_URL}?limit={limit}"
        if offset > 0:
            url += f"&offset={offset}"

        async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if not data.get("success"):
                    logger.error("API returned success=False")
                    return []

                events = data.get("data", {}).get("events", [])
                return events
            except Exception as e:
                logger.error(f"Error fetching events: {e}")
                return []

    async def backfill_historical_data(self, session: AsyncSession) -> int:
        total_saved = 0
        offset = 0
        batch_size = 50

        logger.info(f"Starting historical backfill from {BACKFILL_START_DATE}")

        while True:
            events = await self.fetch_events_page(limit=batch_size, offset=offset)
            if not events:
                logger.info("No more events to fetch")
                break

            oldest_in_batch = None
            saved_count = 0

            for event_data in events:
                news, options = self._parse_event(event_data)
                event_ts = self._get_event_timestamp(event_data)

                if event_ts and event_ts < BACKFILL_START_DATE:
                    logger.info(
                        f"Reached target date {BACKFILL_START_DATE}, stopping backfill"
                    )
                    return total_saved

                if news and await self._save_news_event(session, news):
                    saved_count += 1
                    total_saved += 1

                if options and await self._save_options_event(session, options):
                    saved_count += 1
                    total_saved += 1

                if event_ts:
                    if oldest_in_batch is None or event_ts < oldest_in_batch:
                        oldest_in_batch = event_ts

            await session.commit()
            logger.info(
                f"Batch offset={offset}: saved {saved_count}/{len(events)}, oldest: {oldest_in_batch}"
            )

            if oldest_in_batch and oldest_in_batch < BACKFILL_START_DATE:
                break

            offset += batch_size

            if offset >= 1000:
                logger.warning("Reached offset limit 1000, stopping backfill")
                break

        logger.info(f"Backfill complete. Total saved: {total_saved}")
        return total_saved

    async def fetch_latest_events(self) -> List[Dict[str, Any]]:
        return await self.fetch_events_page(limit=50, offset=0)

    def _get_event_timestamp(self, event: Dict[str, Any]) -> Optional[datetime]:
        ts_str = event.get("timestamp")
        if ts_str:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return None

    def _parse_event(
        self, event: Dict[str, Any]
    ) -> Tuple[Optional[NewsArticle], Optional[OptionsFlow]]:
        """Parse event and return (NewsArticle, OptionsFlow) tuple.
        Only one will be non-None based on event type.
        """
        event_type = event.get("type", "unknown")

        if event_type == "options_alert":
            return None, self._parse_options_event(event)
        else:
            return self._parse_news_event(event), None

    def _parse_options_event(self, event: Dict[str, Any]) -> Optional[OptionsFlow]:
        """Parse options_alert event into OptionsFlow model."""
        try:
            event_id = event.get("id")
            if not event_id:
                return None

            data = event.get("data", {})
            content = data.get("content", "")

            if not content:
                return None

            # Parse timestamp from event
            ts_str = event.get("timestamp")
            if ts_str:
                timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(timezone.utc)

            # Use the options parser
            parsed = parse_message(str(event_id), content, timestamp)
            if not parsed:
                logger.debug(f"Could not parse options event {event_id}")
                return None

            return OptionsFlow(
                message_id=parsed.message_id,
                timestamp=parsed.timestamp,
                interval_type=parsed.interval_type,
                side=parsed.side,
                symbol=parsed.symbol,
                strike=parsed.strike,
                option_type=parsed.option_type,
                expiry=parsed.expiry,
                dte=parsed.dte,
                interval_volume=parsed.interval_volume,
                open_interest=parsed.open_interest,
                vol_oi=parsed.vol_oi,
                otm_percent=parsed.otm_percent,
                bid_percent=parsed.bid_percent,
                ask_percent=parsed.ask_percent,
                premium=parsed.premium,
                avg_fill=parsed.avg_fill,
                multileg_percent=parsed.multileg_percent,
                raw_message=parsed.raw_message,
            )
        except Exception as e:
            logger.error(f"Error parsing options event {event.get('id')}: {e}")
            return None

    def _parse_news_event(self, event: Dict[str, Any]) -> Optional[NewsArticle]:
        """Parse news/kol event into NewsArticle model."""
        try:
            event_id = event.get("id")
            if not event_id:
                return None

            event_type = event.get("type", "unknown")
            data = event.get("data", {})

            # Extract fields
            title = data.get("title")
            original_content = data.get("originalContent")
            translated_content = data.get("translatedContent")
            content = translated_content or original_content or data.get("content", "")

            # KOL tweets often don't have titles, use truncated content
            if not title and content:
                title = content[:50] + "..." if len(content) > 50 else content

            url = data.get("tweetUrl") or data.get("url")  # tweetUrl for kol_tweet
            author = data.get("authorInfo")  # "Name (@handle)"
            symbols = data.get("symbols", [])
            tags = data.get("tags", [])
            importance = data.get("importance", 0)

            # Timestamp
            ts_str = event.get("timestamp")
            if ts_str:
                published_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                published_at = datetime.now(timezone.utc)

            return NewsArticle(
                external_id=str(event_id),
                type=str(event_type),
                title=title,
                content=content,
                original_content=original_content,
                url=url,
                author=author,
                symbols=list(set(symbols)) if symbols else [],
                tags=list(set(tags)) if tags else [],
                importance=int(importance) if importance else 0,
                published_at=published_at,
            )
        except Exception as e:
            logger.error(f"Error parsing news event {event.get('id')}: {e}")
            return None

    async def _save_news_event(
        self, session: AsyncSession, article: NewsArticle
    ) -> bool:
        try:
            stmt = (
                insert(NewsArticle)
                .values(
                    external_id=article.external_id,
                    type=article.type,
                    title=article.title,
                    content=article.content,
                    original_content=article.original_content,
                    url=article.url,
                    author=article.author,
                    symbols=article.symbols,
                    tags=article.tags,
                    importance=article.importance,
                    published_at=article.published_at,
                )
                .on_conflict_do_update(
                    index_elements=["external_id"],
                    set_={
                        "title": article.title,
                        "content": article.content,
                        "original_content": article.original_content,
                        "url": article.url,
                        "author": article.author,
                        "symbols": article.symbols,
                        "tags": article.tags,
                        "importance": article.importance,
                    },
                )
            )
            await session.execute(stmt)
            return True
        except Exception as e:
            logger.error(f"Error saving news event {article.external_id}: {e}")
            return False

    async def _save_options_event(
        self, session: AsyncSession, flow: OptionsFlow
    ) -> bool:
        try:
            stmt = (
                insert(OptionsFlow)
                .values(
                    message_id=flow.message_id,
                    timestamp=flow.timestamp,
                    interval_type=flow.interval_type,
                    side=flow.side,
                    symbol=flow.symbol,
                    strike=flow.strike,
                    option_type=flow.option_type,
                    expiry=flow.expiry,
                    dte=flow.dte,
                    interval_volume=flow.interval_volume,
                    open_interest=flow.open_interest,
                    vol_oi=flow.vol_oi,
                    otm_percent=flow.otm_percent,
                    bid_percent=flow.bid_percent,
                    ask_percent=flow.ask_percent,
                    premium=flow.premium,
                    avg_fill=flow.avg_fill,
                    multileg_percent=flow.multileg_percent,
                    raw_message=flow.raw_message,
                )
                .on_conflict_do_nothing(index_elements=["message_id"])
            )
            await session.execute(stmt)
            return True
        except Exception as e:
            logger.error(f"Error saving options event {flow.message_id}: {e}")
            return False

    async def save_events(self, session: AsyncSession, events: List[Dict[str, Any]]):
        news_count = 0
        options_count = 0

        for event_data in events:
            news, options = self._parse_event(event_data)

            if news and await self._save_news_event(session, news):
                news_count += 1

            if options and await self._save_options_event(session, options):
                options_count += 1

        await session.commit()
        logger.info(f"Processed {news_count} news, {options_count} options events")
