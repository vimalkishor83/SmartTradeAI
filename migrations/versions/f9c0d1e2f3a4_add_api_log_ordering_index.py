"""add stable API log ordering index

Revision ID: f9c0d1e2f3a4
Revises: f8b9c0d1e2f3
"""

from alembic import op


revision = "f9c0d1e2f3a4"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "idx_api_logs_config_time_id",
        "api_logs",
        ["api_config_id", "created_at", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_api_logs_config_time_id", table_name="api_logs")
