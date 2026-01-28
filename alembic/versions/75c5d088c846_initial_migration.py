"""Initial migration

Revision ID: 75c5d088c846
Revises:
Create Date: 2026-01-17 13:51:32.895711

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "75c5d088c846"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # options_flow
    op.create_table(
        "options_flow",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_type", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("option_type", sa.String(length=2), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("dte", sa.Integer(), nullable=False),
        sa.Column("interval_volume", sa.Integer(), nullable=False),
        sa.Column("open_interest", sa.Integer(), nullable=False),
        sa.Column("vol_oi", sa.Float(), nullable=False),
        sa.Column("otm_percent", sa.Float(), nullable=False),
        sa.Column("bid_percent", sa.Integer(), nullable=False),
        sa.Column("ask_percent", sa.Integer(), nullable=False),
        sa.Column("premium", sa.Float(), nullable=False),
        sa.Column("avg_fill", sa.Float(), nullable=False),
        sa.Column("multileg_percent", sa.Float(), nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("idx_timestamp", "options_flow", ["timestamp"], unique=False)
    op.create_index(
        "ix_options_flow_option_type", "options_flow", ["option_type"], unique=False
    )
    op.create_index("ix_options_flow_side", "options_flow", ["side"], unique=False)
    op.create_index("ix_options_flow_symbol", "options_flow", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_options_flow_symbol", table_name="options_flow")
    op.drop_index("ix_options_flow_side", table_name="options_flow")
    op.drop_index("ix_options_flow_option_type", table_name="options_flow")
    op.drop_index("idx_timestamp", table_name="options_flow")
    op.drop_table("options_flow")
