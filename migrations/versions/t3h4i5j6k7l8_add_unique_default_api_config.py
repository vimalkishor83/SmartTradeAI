"""enforce one default API config per market"""

from alembic import op
import sqlalchemy as sa


revision = "t3h4i5j6k7l8"
down_revision = "s2g3h4i5j6k7"
branch_labels = None
depends_on = None


def upgrade():
    # The application clears competing defaults, but only a database
    # constraint closes the concurrent-request race window.
    conn = op.get_bind()
    duplicates = conn.execute(sa.text(
        "SELECT market, MIN(id) AS keep_id FROM api_configs "
        "WHERE is_default IS TRUE GROUP BY market HAVING COUNT(*) > 1"
    )).fetchall()
    for market, keep_id in duplicates:
        conn.execute(sa.text(
            "UPDATE api_configs SET is_default = false "
            "WHERE market = :market AND is_default IS TRUE AND id <> :keep_id"
        ), {"market": market, "keep_id": keep_id})
    op.create_index(
        "uq_api_configs_default_market",
        "api_configs",
        ["market"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default IS TRUE"),
    )


def downgrade():
    op.drop_index("uq_api_configs_default_market", table_name="api_configs")
