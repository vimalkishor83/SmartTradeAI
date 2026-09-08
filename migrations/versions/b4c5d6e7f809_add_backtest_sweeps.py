"""add persisted strategy sweep reports

Revision ID: b4c5d6e7f809
Revises: f5e6a7b8c9d0
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f809"
down_revision = "f5e6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backtest_sweeps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assets", sa.JSON(), nullable=False),
        sa.Column("strategies", sa.JSON(), nullable=False),
        sa.Column("timeframes", sa.JSON(), nullable=False),
        sa.Column("candle_limit", sa.Integer(), nullable=False),
        sa.Column("initial_capital", sa.Float(), nullable=False),
        sa.Column("commission", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.Column("spread", sa.Float(), nullable=False),
        sa.Column("total_cells", sa.Integer(), nullable=False),
        sa.Column("completed_cells", sa.Integer(), nullable=False),
        sa.Column("result_data", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_sweeps_user_id", "backtest_sweeps", ["user_id"], unique=False)
    op.create_index("ix_backtest_sweeps_created_at", "backtest_sweeps", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_backtest_sweeps_created_at", table_name="backtest_sweeps")
    op.drop_index("ix_backtest_sweeps_user_id", table_name="backtest_sweeps")
    op.drop_table("backtest_sweeps")
