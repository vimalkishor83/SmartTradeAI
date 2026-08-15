"""add platform_config table

Merges two pre-existing divergent heads (7daaf6446589 and a7b8c9d0e1f2 —
already unmerged before this change) in addition to adding the new table,
so this becomes the single head going forward.

Revision ID: d07e8fbd6e1c
Revises: 7daaf6446589, a7b8c9d0e1f2
Create Date: 2026-08-15 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd07e8fbd6e1c'
down_revision = ('7daaf6446589', 'a7b8c9d0e1f2')
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('platform_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('disabled_nav_items', sa.JSON(), nullable=True),
        sa.Column('timeframes', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('platform_config')
