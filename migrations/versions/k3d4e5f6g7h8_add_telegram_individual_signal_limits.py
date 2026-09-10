"""add standalone personal Telegram signal limits

Revision ID: k3d4e5f6g7h8
Revises: j2c3d4e5f6g7
"""

from alembic import op
import sqlalchemy as sa


revision = "k3d4e5f6g7h8"
down_revision = "j2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_individual_signal_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("asset_ids", sa.JSON(), nullable=True),
        sa.Column("timeframes", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("telegram_individual_signal_limits")
