"""add source column to news_articles

Revision ID: a1b2c3d4e5f6
Revises: c6b11f2f2c9d
Create Date: 2026-02-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "c6b11f2f2c9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 source 字段
    op.add_column(
        "news_articles",
        sa.Column("source", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_news_articles_source"),
        "news_articles",
        ["source"],
        unique=False,
    )
    # 一次性操作：将现有历史数据标记为 bubbleseek 来源
    op.execute("UPDATE news_articles SET source = 'bubbleseek' WHERE source IS NULL")


def downgrade() -> None:
    op.drop_index(op.f("ix_news_articles_source"), table_name="news_articles")
    op.drop_column("news_articles", "source")
