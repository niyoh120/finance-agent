"""add news_articles table

Revision ID: 9bfd6d725b27
Revises: 75c5d088c846
Create Date: 2026-01-18 10:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9bfd6d725b27"
down_revision = "75c5d088c846"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("symbols", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(
        op.f("ix_news_articles_external_id"),
        "news_articles",
        ["external_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_news_articles_published_at"),
        "news_articles",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_articles_type"), "news_articles", ["type"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_news_articles_type"), table_name="news_articles")
    op.drop_index(op.f("ix_news_articles_published_at"), table_name="news_articles")
    op.drop_index(op.f("ix_news_articles_external_id"), table_name="news_articles")
    op.drop_table("news_articles")
