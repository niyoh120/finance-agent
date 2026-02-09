import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from shared.models import NewsArticle
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

API_BASE_URL = "https://news.futunn.com/news-site-api/main/get-flash-list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://news.futunn.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def convert_futu_code(code: str) -> str | None:
    """转换富途代码格式，去掉后缀。

    "AAPL.US" -> "AAPL"
    "00700.HK" -> "00700"
    "BTC.CC" -> "BTC"
    """
    if not code or "." not in code:
        return None
    symbol, _ = code.rsplit(".", 1)
    return symbol


class FutunnScraper:
    async def get_latest_futunn_news_time(
        self, session: AsyncSession
    ) -> datetime | None:
        """获取数据库中最新的富途新闻时间。"""
        stmt = (
            select(NewsArticle.published_at)
            .where(NewsArticle.source == "futunn")
            .order_by(NewsArticle.published_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def fetch_news_page(
        self, page_size: int = 30, seq_mark: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        """获取一页新闻数据。

        返回: (news_list, next_seq_mark, has_more)
        """
        params = {"pageSize": str(page_size), "lang": "zh-cn"}
        if seq_mark:
            params["seqMark"] = seq_mark

        async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
            try:
                response = await client.get(API_BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("code") != 0:
                    logger.error(f"API returned error code: {data.get('code')}")
                    return [], None, False

                inner_data = data.get("data", {}).get("data", {})
                news_list = inner_data.get("news", [])
                next_seq_mark = inner_data.get("seqMark")
                has_more = inner_data.get("hasMore", False)

                return news_list, next_seq_mark, has_more
            except Exception as e:
                logger.error(f"Error fetching news: {e}")
                return [], None, False

    async def backfill_historical_data(
        self, session: AsyncSession, backfill_days: int = 60
    ) -> int:
        """回填历史数据。"""
        total_saved = 0
        seq_mark = None
        cutoff_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=backfill_days)

        logger.info(f"Starting historical backfill until {cutoff_time}")

        while True:
            news_list, next_seq_mark, has_more = await self.fetch_news_page(
                page_size=30, seq_mark=seq_mark
            )

            if not news_list:
                logger.info("No more news to fetch")
                break

            oldest_in_batch = None
            saved_count = 0

            for news_item in news_list:
                article = self._parse_news_item(news_item)
                if not article:
                    continue

                if article.published_at < cutoff_time:
                    logger.info(f"Reached cutoff date {cutoff_time}, stopping backfill")
                    await session.commit()
                    return total_saved

                if await self._save_news_article(session, article):
                    saved_count += 1
                    total_saved += 1

                if oldest_in_batch is None or article.published_at < oldest_in_batch:
                    oldest_in_batch = article.published_at

            await session.commit()
            logger.info(
                f"Batch saved {saved_count}/{len(news_list)}, oldest: {oldest_in_batch}"
            )

            if not has_more or not next_seq_mark:
                break

            seq_mark = next_seq_mark

            # 安全限制
            if total_saved >= 1000:
                logger.warning("Reached max backfill limit 1000, stopping")
                break

        logger.info(f"Backfill complete. Total saved: {total_saved}")
        return total_saved

    async def fetch_latest_news(self) -> list[dict[str, Any]]:
        """获取最新一页新闻。"""
        news_list, _, _ = await self.fetch_news_page(page_size=30)
        return news_list

    def _parse_news_item(self, news_item: dict[str, Any]) -> NewsArticle | None:
        """解析单条新闻为 NewsArticle 模型。"""
        try:
            news_id = news_item.get("id")
            if not news_id:
                return None

            content = news_item.get("content", "")
            if not content:
                return None

            title = news_item.get("title") or ""
            if not title and content:
                title = content[:50] + "..." if len(content) > 50 else content

            # 时间戳转换 (秒)
            time_str = news_item.get("time")
            if time_str:
                published_at = datetime.fromtimestamp(int(time_str), tz=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)

            # 提取股票代码
            quote_list = news_item.get("quote", [])
            symbols = []
            for quote in quote_list:
                code = quote.get("code")
                if code:
                    symbol = convert_futu_code(code)
                    if symbol:
                        symbols.append(symbol)
            symbols = list(set(symbols))  # 去重

            # 根据是否有股票关联确定类型
            news_type = "stock_news" if symbols else "macro_news"

            url = news_item.get("detailUrl", "")
            importance = news_item.get("level", 0)

            return NewsArticle(
                external_id=f"futunn_{news_id}",
                type=news_type,
                source="futunn",
                title=title,
                content=content,
                original_content=None,
                url=url,
                author=None,
                symbols=symbols,
                tags=[],
                importance=int(importance) if importance else 0,
                published_at=published_at,
            )
        except Exception as e:
            logger.error(f"Error parsing news item {news_item.get('id')}: {e}")
            return None

    async def _save_news_article(
        self, session: AsyncSession, article: NewsArticle
    ) -> bool:
        """保存新闻到数据库 (UPSERT)。"""
        try:
            stmt = (
                insert(NewsArticle)
                .values(
                    external_id=article.external_id,
                    type=article.type,
                    source=article.source,
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
                        "url": article.url,
                        "symbols": article.symbols,
                        "importance": article.importance,
                    },
                )
            )
            await session.execute(stmt)
            return True
        except Exception as e:
            logger.error(f"Error saving news {article.external_id}: {e}")
            return False

    async def save_news(
        self, session: AsyncSession, news_list: list[dict[str, Any]]
    ) -> int:
        """批量保存新闻。"""
        saved_count = 0

        for news_item in news_list:
            article = self._parse_news_item(news_item)
            if article and await self._save_news_article(session, article):
                saved_count += 1

        await session.commit()
        logger.info(f"Processed {saved_count}/{len(news_list)} news articles")
        return saved_count
