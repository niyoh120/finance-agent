from collections.abc import AsyncGenerator
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OptionsFlow(Base):
    __tablename__ = "options_flow"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval_type: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strike: Mapped[float] = mapped_column(Float, nullable=False)
    option_type: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    dte: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_volume: Mapped[int] = mapped_column(Integer, nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, nullable=False)
    vol_oi: Mapped[float] = mapped_column(Float, nullable=False)
    otm_percent: Mapped[float] = mapped_column(Float, nullable=False)
    bid_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    ask_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    premium: Mapped[float] = mapped_column(Float, nullable=False)
    avg_fill: Mapped[float] = mapped_column(Float, nullable=False)
    multileg_percent: Mapped[float] = mapped_column(Float, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (Index("idx_timestamp", "timestamp"),)

    def __repr__(self) -> str:
        return f"<OptionsFlow {self.symbol} {self.strike}{self.option_type} {self.side}>"


DATABASE_PATH = Path(__file__).parent.parent.parent / "data" / "options_flow.db"


def get_database_url(db_path: Path | None = None) -> str:
    path = db_path or DATABASE_PATH
    return f"sqlite+aiosqlite:///{path}"


def create_engine(db_path: Path | None = None):
    url = get_database_url(db_path)
    return create_async_engine(url, echo=False)


def create_session_maker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(db_path: Path | None = None) -> None:
    path = db_path or DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session(db_path: Path | None = None) -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(db_path)
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        yield session
