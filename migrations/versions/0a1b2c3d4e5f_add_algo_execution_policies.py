"""add per-user Delta algo execution policies"""

from alembic import op
import sqlalchemy as sa


revision = "0a1b2c3d4e5f"
down_revision = "f9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "algo_execution_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("execution_provider", sa.String(length=40), nullable=False, server_default="delta_exchange_india"),
        sa.Column("mode", sa.String(length=10), nullable=False, server_default="paper"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_margin_amount", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("max_notional_amount", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("max_leverage", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_open_positions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_daily_loss", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("max_slippage_bps", sa.Numeric(10, 4), nullable=False, server_default="50"),
        sa.Column("order_rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("algo_execution_policies")
