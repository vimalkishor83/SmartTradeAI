"""add per-user telegram alert preferences

Revision ID: q2e3f4a5b6c7
Revises: p1d2e3f4a5b6
"""

from alembic import op
import sqlalchemy as sa


revision = "q2e3f4a5b6c7"
down_revision = "p1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telegram_user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("markets", sa.JSON(), nullable=True),
        sa.Column("asset_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade():
    op.drop_table("telegram_user_preferences")
