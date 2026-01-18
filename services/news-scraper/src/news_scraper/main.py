import asyncio
import logging
import os
import signal
import sys

# Ensure shared package is available
try:
    from shared.database import session_scope
except ImportError:
    # If running locally without installing shared, might need to adjust path
    sys.path.append(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    )
    from shared.database import session_scope

from scraper import BubbleSeekScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_scraper():
    scraper = BubbleSeekScraper()
    first_run = True

    while True:
        try:
            if first_run:
                async with session_scope() as session:
                    latest_time = await scraper.get_latest_published_time(session)

                    if latest_time is None:
                        logger.info(
                            "Database is empty, starting historical backfill..."
                        )
                        await scraper.backfill_historical_data(session)
                    else:
                        logger.info(f"Found existing data, latest: {latest_time}")

                first_run = False

            logger.info("Starting crawl cycle...")
            events = await scraper.fetch_latest_news()

            if events:
                async with session_scope() as session:
                    await scraper.save_events(session, events)

            sleep_time = int(os.getenv("SCRAPE_INTERVAL", "60"))
            logger.info(f"Sleeping for {sleep_time} seconds...")
            await asyncio.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            await asyncio.sleep(60)


async def main():
    logger.info("Starting News Scraper Service")

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
    import uvloop

    uvloop.install()

    asyncio.run(main())
