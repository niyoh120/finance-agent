import asyncio
import os
import yaml
import aiohttp
from datetime import datetime, timezone

# Fix import path for shared
# In Docker, shared is installed as package.
# Locally, we might need to adjust path or rely on workspace.
from shared.database import session_scope
from shared.models.stocks import StockPrice
from sqlalchemy.dialects.postgresql import insert


async def fetch_quote(session, symbol):
    url = os.getenv("STOCK_API_URL", "http://stock-api:3000")
    try:
        async with session.get(f"{url}/quote", params={"symbol": symbol}) as resp:
            if resp.status == 200:
                return await resp.json()
            print(f"Failed to fetch {symbol}: {resp.status}")
            return None
    except Exception as e:
        print(f"Connection error to {url}: {e}")
        return None


async def save_quote(quote_data, timeframe):
    async with session_scope() as session:
        ts = datetime.fromtimestamp(quote_data["timestamp"] / 1000, tz=timezone.utc)

        # Handle possible nulls from API
        price = quote_data.get("price", 0.0)

        stmt = insert(StockPrice).values(
            symbol=quote_data["symbol"],
            timestamp=ts,
            timeframe=timeframe,
            open=quote_data.get("open") or price,
            high=quote_data.get("high") or price,
            low=quote_data.get("low") or price,
            close=price,
            volume=quote_data.get("volume") or 0,
        )

        stmt = stmt.on_conflict_do_update(
            constraint="uq_stock_price",
            set_={
                "close": stmt.excluded.close,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "volume": stmt.excluded.volume,
            },
        )
        await session.execute(stmt)


async def main():
    config_path = os.getenv("CONFIG_PATH", "config.yaml")
    if not os.path.exists(config_path):
        print(f"Config not found at {config_path}")
        return

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    symbols = config.get("symbols", [])
    timeframe = str(config.get("timeframe", "1D"))
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    print(
        f"Starting Stock Scraper. Polling {len(symbols)} symbols every {poll_interval}s."
    )

    async with aiohttp.ClientSession() as http_session:
        while True:
            start_time = datetime.now()
            print("Fetching quotes...")
            for symbol in symbols:
                try:
                    data = await fetch_quote(http_session, symbol)
                    if data:
                        await save_quote(data, timeframe)
                        print(f"Saved {symbol}: {data.get('price')}")
                except Exception as e:
                    print(f"Error processing {symbol}: {e}")

            elapsed = (datetime.now() - start_time).total_seconds()
            sleep_time = max(1, poll_interval - elapsed)
            print(f"Sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)


if __name__ == "__main__":
    asyncio.run(main())
