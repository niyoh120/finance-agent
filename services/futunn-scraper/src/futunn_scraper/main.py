import asyncio
import logging
import os
import signal

from shared.database import session_scope
from shared.logging import configure_logging

from .scraper import FutunnScraper

configure_logging(service="futunn-scraper")
logger = logging.getLogger(__name__)


async def run_scraper():
    scraper = FutunnScraper()
    first_run = True

    while True:
        try:
            if first_run:
                async with session_scope() as session:
                    latest_time = await scraper.get_latest_futunn_news_time(session)

                    if latest_time is None:
                        backfill_days = int(
                            os.getenv("FA_FUTUNN_SCRAPER_BACKFILL_DAYS", "60")
                        )
                        logger.info(
                            f"No futunn news in database, starting historical backfill for {backfill_days} days..."
                        )
                        await scraper.backfill_historical_data(
                            session, backfill_days=backfill_days
                        )
                    else:
                        logger.info(
                            f"Found existing futunn data, latest: {latest_time}"
                        )

                first_run = False

            logger.info("Starting crawl cycle...")
            news_list = await scraper.fetch_latest_news()

            if news_list:
                async with session_scope() as session:
                    await scraper.save_news(session, news_list)

            sleep_time = int(os.getenv("FA_FUTUNN_SCRAPER_INTERVAL", "60"))
            logger.info(f"Sleeping for {sleep_time} seconds...")
            await asyncio.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            await asyncio.sleep(60)


async def main():
    logger.info("Starting Futunn Scraper Service")

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    scraper_task = asyncio.create_task(run_scraper())

    await stop_event.wait()
    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        logger.info("Scraper task cancelled")

    logger.info("Service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
