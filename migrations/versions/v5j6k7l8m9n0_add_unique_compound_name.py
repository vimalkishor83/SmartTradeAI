"""prevent duplicate saved compound-calculation names"""

from alembic import op


revision = "v5j6k7l8m9n0"
down_revision = "u4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX uq_daily_compound_calculation_name_lower "
        "ON daily_compound_calculations (lower(name))"
    )


def downgrade():
    op.drop_index("uq_daily_compound_calculation_name_lower", table_name="daily_compound_calculations")
