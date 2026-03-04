"""add macro tables

Revision ID: c6b11f2f2c9d
Revises: 9bfd6d725b27
Create Date: 2026-01-27 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c6b11f2f2c9d"
down_revision = "9bfd6d725b27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("current_snapshot_date", sa.Date(), nullable=True),
        sa.Column("compare_date", sa.Date(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_score", sa.Float(), nullable=True),
        sa.Column("compare_score", sa.Float(), nullable=True),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_date", name="uq_macro_report"),
    )
    op.create_index("idx_macro_report_date", "macro_reports", ["report_date"], unique=False)

    op.create_table(
        "macro_module_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("module_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("name_cn", sa.String(length=128), nullable=True),
        sa.Column("current_score", sa.Float(), nullable=True),
        sa.Column("compare_score", sa.Float(), nullable=True),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_date", "module_id", name="uq_macro_module_snapshot"),
    )
    op.create_index(
        "idx_macro_module_snapshot_report",
        "macro_module_snapshots",
        ["report_date"],
        unique=False,
    )
    op.create_index(
        "idx_macro_module_snapshot_module",
        "macro_module_snapshots",
        ["module_id"],
        unique=False,
    )

    op.create_table(
        "macro_factor_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("module_id", sa.String(length=32), nullable=False),
        sa.Column("module_name", sa.String(length=128), nullable=True),
        sa.Column("module_name_cn", sa.String(length=128), nullable=True),
        sa.Column("factor_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("name_cn", sa.String(length=128), nullable=True),
        sa.Column("display_only", sa.Boolean(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("current_value_formatted", sa.String(length=64), nullable=True),
        sa.Column("current_percentile", sa.Float(), nullable=True),
        sa.Column("compare_value", sa.Float(), nullable=True),
        sa.Column("compare_value_formatted", sa.String(length=64), nullable=True),
        sa.Column("compare_percentile", sa.Float(), nullable=True),
        sa.Column("value_change", sa.Float(), nullable=True),
        sa.Column("value_change_pct", sa.Float(), nullable=True),
        sa.Column("percentile_change", sa.Float(), nullable=True),
        sa.Column("percentile_change_pct", sa.Float(), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_date", "module_id", "factor_id", name="uq_macro_factor_snapshot"),
    )
    op.create_index(
        "idx_macro_factor_snapshot_report",
        "macro_factor_snapshots",
        ["report_date"],
        unique=False,
    )
    op.create_index(
        "idx_macro_factor_snapshot_module",
        "macro_factor_snapshots",
        ["module_id"],
        unique=False,
    )
    op.create_index(
        "idx_macro_factor_snapshot_factor",
        "macro_factor_snapshots",
        ["factor_id"],
        unique=False,
    )

    op.create_table(
        "macro_module_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("module_id", sa.String(length=32), nullable=False),
        sa.Column("module_name", sa.String(length=128), nullable=True),
        sa.Column("module_name_cn", sa.String(length=128), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("percentile", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_id", "date", name="uq_macro_module_history"),
    )
    op.create_index(
        "idx_macro_module_history_date",
        "macro_module_history",
        ["date"],
        unique=False,
    )
    op.create_index(
        "idx_macro_module_history_module",
        "macro_module_history",
        ["module_id"],
        unique=False,
    )

    op.create_table(
        "macro_total_index_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("percentile", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_macro_total_index_history"),
    )
    op.create_index(
        "idx_macro_total_index_date",
        "macro_total_index_history",
        ["date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_macro_total_index_date", table_name="macro_total_index_history")
    op.drop_table("macro_total_index_history")

    op.drop_index("idx_macro_module_history_module", table_name="macro_module_history")
    op.drop_index("idx_macro_module_history_date", table_name="macro_module_history")
    op.drop_table("macro_module_history")

    op.drop_index("idx_macro_factor_snapshot_factor", table_name="macro_factor_snapshots")
    op.drop_index("idx_macro_factor_snapshot_module", table_name="macro_factor_snapshots")
    op.drop_index("idx_macro_factor_snapshot_report", table_name="macro_factor_snapshots")
    op.drop_table("macro_factor_snapshots")

    op.drop_index("idx_macro_module_snapshot_module", table_name="macro_module_snapshots")
    op.drop_index("idx_macro_module_snapshot_report", table_name="macro_module_snapshots")
    op.drop_table("macro_module_snapshots")

    op.drop_index("idx_macro_report_date", table_name="macro_reports")
    op.drop_table("macro_reports")
