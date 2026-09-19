"""add visitor_logs table for new-IP/new-device homepage alerts

Revision ID: r1f2g3h4i5j6
Revises: q2e3f4a5b6c7
"""

from alembic import op
import sqlalchemy as sa


revision = "r1f2g3h4i5j6"
down_revision = "q2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "visitor_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ip_address", sa.String(length=50), nullable=False),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("ip_address", "user_agent", name="uq_visitor_logs_ip_ua"),
    )
    op.create_index("ix_visitor_logs_ip_address", "visitor_logs", ["ip_address"])


def downgrade():
    op.drop_index("ix_visitor_logs_ip_address", table_name="visitor_logs")
    op.drop_table("visitor_logs")
