from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    symbols: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)

    importance: Mapped[int] = mapped_column(Integer, default=0)

    source: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )  # 数据来源: "futunn", "bubbleseek" 等

    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<NewsArticle {self.type} {self.external_id}>"
