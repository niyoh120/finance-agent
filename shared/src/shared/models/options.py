from datetime import date, datetime
from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class OptionsFlow(Base):
    __tablename__ = "options_flow"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Using timezone=True for Postgres TIMESTAMPTZ
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_timestamp", "timestamp"),)

    def __repr__(self) -> str:
        return f"<OptionsFlow {self.symbol} {self.strike}{self.option_type} {self.side}>"
