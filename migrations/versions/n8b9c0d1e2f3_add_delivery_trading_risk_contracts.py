"""add bounded notification delivery, paper orders and risk limits

Revision ID: n8b9c0d1e2f3
Revises: m7a8b9c0d1e2
"""

from alembic import op
import sqlalchemy as sa


revision = "n8b9c0d1e2f3"
down_revision = "m7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("delivery_status", sa.String(length=20), nullable=False,
                                      server_default="pending"))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False,
                                      server_default="0"))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("skipped_reason", sa.String(length=120), nullable=True))
        batch_op.create_index(
            "idx_notif_delivery_due",
            ["delivery_status", "next_attempt_at", "created_at", "id"],
            unique=False,
        )

    op.create_table(
        "trade_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("broker_order_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_trade_request_user_key"),
    )
    op.create_index("idx_trade_request_user_created", "trade_requests", ["user_id", "created_at"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("stop_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="accepted"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "client_order_id", name="uq_paper_order_user_client_id"),
    )
    op.create_index("idx_paper_order_user_status", "paper_orders", ["user_id", "status"])

    op.create_table(
        "risk_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_daily_loss", sa.Numeric(precision=24, scale=8), nullable=False, server_default="0"),
        sa.Column("max_drawdown_pct", sa.Numeric(precision=10, scale=4), nullable=False, server_default="0"),
        sa.Column("max_total_exposure", sa.Numeric(precision=24, scale=8), nullable=False, server_default="0"),
        sa.Column("max_correlated_exposure", sa.Numeric(precision=24, scale=8), nullable=False, server_default="0"),
        sa.Column("max_open_risk", sa.Numeric(precision=24, scale=8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_risk_limit_user"),
    )
    op.create_index("idx_risk_limits_user", "risk_limits", ["user_id"], unique=True)


def downgrade():
    op.drop_index("idx_risk_limits_user", table_name="risk_limits")
    op.drop_table("risk_limits")
    op.drop_index("idx_paper_order_user_status", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("idx_trade_request_user_created", table_name="trade_requests")
    op.drop_table("trade_requests")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("idx_notif_delivery_due")
        batch_op.drop_column("skipped_reason")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("last_error")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("delivery_status")
