import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import NewsArticle

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.bubbleseek.ai/api/events/public"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://bubbleseek.ai/",
    "Origin": "https://bubbleseek.ai",
}
BACKFILL_START_DATE = datetime(2025, 12, 1, tzinfo=timezone.utc)


class BubbleSeekScraper:
    async def get_latest_published_time(
        self, session: AsyncSession
    ) -> Optional[datetime]:
        stmt = (
            select(NewsArticle.published_at)
            .order_by(desc(NewsArticle.published_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        latest = result.scalar_one_or_none()
        return latest

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
                logger.error(f"Error fetching news: {e}")
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
                article = self.parse_event(event_data)
                if not article:
                    continue

                if article.published_at < BACKFILL_START_DATE:
                    logger.info(
                        f"Reached target date {BACKFILL_START_DATE}, stopping backfill"
                    )
                    return total_saved

                if await self._save_single_event(session, article):
                    saved_count += 1
                    total_saved += 1

                if oldest_in_batch is None or article.published_at < oldest_in_batch:
                    oldest_in_batch = article.published_at

            await session.commit()
            logger.info(
                f"Batch offset={offset}: saved {saved_count}/{len(events)}, oldest: {oldest_in_batch}"
            )

            if oldest_in_batch and oldest_in_batch < BACKFILL_START_DATE:
                break

            offset += batch_size

            if offset >= 1000:
                logger.warning(f"Reached offset limit 1000, stopping backfill")
                break

        logger.info(f"Backfill complete. Total saved: {total_saved}")
        return total_saved

    async def fetch_latest_news(self) -> List[Dict[str, Any]]:
        return await self.fetch_events_page(limit=50, offset=0)

    def parse_event(self, event: Dict[str, Any]) -> Optional[NewsArticle]:
        try:
            event_id = event.get("id")
            if not event_id:
                return None

            event_type = event.get("type", "unknown")
            if event_type == "options_alert":
                return None

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
            logger.error(f"Error parsing event {event.get('id')}: {e}")
            return None

    async def _save_single_event(
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
            logger.error(f"Error saving event {article.external_id}: {e}")
            return False

    async def save_events(self, session: AsyncSession, events: List[Dict[str, Any]]):
        count = 0
        for event_data in events:
            article = self.parse_event(event_data)
            if not article:
                continue

            if await self._save_single_event(session, article):
                count += 1

        logger.info(f"Processed {count} events")
