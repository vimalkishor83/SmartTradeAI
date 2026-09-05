"""add expiry tracking to live read logs

Revision ID: 5d9e0f1a2b3c
Revises: 4c8d9e0f1a2b
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "5d9e0f1a2b3c"
down_revision = "4c8d9e0f1a2b"
branch_labels = None
depends_on = None


_EXPIRY_MINUTES = {
    "1m": 5,
    "5m": 20,
    "15m": 60,
    "30m": 120,
    "1h": 240,
    "2h": 480,
    "4h": 960,
    "1d": 2880,
}


def upgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_live_read_logs_expires_at", ["expires_at"], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        case_sql = " ".join(
            f"WHEN '{timeframe}' THEN interval '{minutes} minutes'"
            for timeframe, minutes in _EXPIRY_MINUTES.items()
        )
        op.execute(sa.text(
            "UPDATE live_read_logs "
            "SET expires_at = generated_at + CASE timeframe "
            f"{case_sql} ELSE interval '240 minutes' END "
            "WHERE expires_at IS NULL AND generated_at IS NOT NULL"
        ))
    else:
        case_sql = " ".join(
            f"WHEN '{timeframe}' THEN '+{minutes} minutes'"
            for timeframe, minutes in _EXPIRY_MINUTES.items()
        )
        op.execute(sa.text(
            "UPDATE live_read_logs "
            "SET expires_at = datetime(generated_at, CASE timeframe "
            f"{case_sql} ELSE '+240 minutes' END) "
            "WHERE expires_at IS NULL AND generated_at IS NOT NULL"
        ))


def downgrade():
    with op.batch_alter_table("live_read_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_live_read_logs_expires_at")
        batch_op.drop_column("expires_at")
