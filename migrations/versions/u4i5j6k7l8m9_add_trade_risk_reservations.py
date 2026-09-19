"""store durable exposure reservations for live trade requests"""

from alembic import op
import sqlalchemy as sa


revision = "u4i5j6k7l8m9"
down_revision = "t3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("trade_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("requested_exposure", sa.Numeric(24, 8), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("requested_open_risk", sa.Numeric(24, 8), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("trade_requests", schema=None) as batch_op:
        batch_op.drop_column("requested_open_risk")
        batch_op.drop_column("requested_exposure")
