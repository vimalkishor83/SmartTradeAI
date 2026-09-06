"""add daily_compound_calculations table

Revision ID: b7c8d9e0f1a2
Revises: 0a1b2c3d4e5f
Create Date: 2026-09-06 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "daily_compound_calculations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("principal", sa.Float(), nullable=False),
        sa.Column("rate_percent", sa.Float(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("duration_value", sa.Integer(), nullable=False),
        sa.Column("duration_unit", sa.String(length=10), nullable=False),
        sa.Column("frequency", sa.String(length=12), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_daily_compound_calc_created_by",
        "daily_compound_calculations",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_daily_compound_calc_created_by", table_name="daily_compound_calculations")
    op.drop_table("daily_compound_calculations")
