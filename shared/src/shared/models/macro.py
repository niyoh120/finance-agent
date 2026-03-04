from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class MacroReport(Base):
    __tablename__ = "macro_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    current_snapshot_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    compare_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    compare_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("report_date", name="uq_macro_report"),
        Index("idx_macro_report_date", "report_date"),
    )


class MacroModuleSnapshot(Base):
    __tablename__ = "macro_module_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    module_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_cn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    compare_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("report_date", "module_id", name="uq_macro_module_snapshot"),
        Index("idx_macro_module_snapshot_report", "report_date"),
        Index("idx_macro_module_snapshot_module", "module_id"),
    )


class MacroFactorSnapshot(Base):
    __tablename__ = "macro_factor_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    module_id: Mapped[str] = mapped_column(String(32), nullable=False)
    module_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_name_cn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    factor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name_cn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value_formatted: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    compare_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    compare_value_formatted: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compare_percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("report_date", "module_id", "factor_id", name="uq_macro_factor_snapshot"),
        Index("idx_macro_factor_snapshot_report", "report_date"),
        Index("idx_macro_factor_snapshot_module", "module_id"),
        Index("idx_macro_factor_snapshot_factor", "factor_id"),
    )


class MacroModuleHistory(Base):
    __tablename__ = "macro_module_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[str] = mapped_column(String(32), nullable=False)
    module_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_name_cn: Mapped[str | None] = mapped_column(String(128), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("module_id", "date", name="uq_macro_module_history"),
        Index("idx_macro_module_history_date", "date"),
        Index("idx_macro_module_history_module", "module_id"),
    )


class MacroTotalIndexHistory(Base):
    __tablename__ = "macro_total_index_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("date", name="uq_macro_total_index_history"),
        Index("idx_macro_total_index_date", "date"),
    )
