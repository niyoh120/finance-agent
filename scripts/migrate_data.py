import asyncio
import os
import aiosqlite
from dateutil import parser
from shared.database import session_scope
from shared.models.options import OptionsFlow
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import text


async def insert_batch(session, batch):
    if not batch:
        return
    stmt = insert(OptionsFlow).values(batch)
    stmt = stmt.on_conflict_do_nothing(index_elements=["message_id"])
    await session.execute(stmt)


def parse_row(row):
    d = dict(row)
    # Parse timestamp
    if isinstance(d.get("timestamp"), str):
        try:
            d["timestamp"] = parser.parse(d["timestamp"])
        except Exception:
            pass

    # Parse expiry
    if isinstance(d.get("expiry"), str):
        try:
            d["expiry"] = parser.parse(d["expiry"]).date()
        except Exception:
            pass

    # Parse created_at
    if isinstance(d.get("created_at"), str):
        try:
            d["created_at"] = parser.parse(d["created_at"])
        except Exception:
            pass

    return d


async def migrate():
    sqlite_path = os.getenv("SQLITE_PATH", "data/options_flow.db")
    if not os.path.exists(sqlite_path):
        print(f"No SQLite DB found at {sqlite_path}")
        return

    print(f"Migrating from {sqlite_path}...")

    async with aiosqlite.connect(sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM options_flow") as cursor:
            rows = await cursor.fetchall()
            print(f"Found {len(rows)} records.")

            async with session_scope() as session:
                count = 0
                batch = []
                for row in rows:
                    data = parse_row(row)
                    batch.append(data)
                    count += 1

                    if len(batch) >= 1000:
                        await insert_batch(session, batch)
                        batch = []
                        print(f"Migrated {count}...")

                if batch:
                    await insert_batch(session, batch)
                    print(f"Migrated {count} (Final).")

                # Update sequence
                print("Updating sequence...")
                try:
                    await session.execute(
                        text(
                            "SELECT setval('options_flow_id_seq', (SELECT MAX(id) FROM options_flow));"
                        )
                    )
                except Exception as e:
                    print(f"Sequence update failed (maybe empty?): {e}")


if __name__ == "__main__":
    asyncio.run(migrate())
