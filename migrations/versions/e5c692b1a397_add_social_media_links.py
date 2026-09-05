"""Add social media link fields to platform_config

Every field is nullable/empty by default and stays empty until an admin
pastes a real, official account URL from /admin/platform-config — never
auto-populated. Public pages only render an icon for a platform with a
non-empty value here (see GET /api/v1/public/site-config).

Revision ID: e5c692b1a397
Revises: 61f93ce4cf3e
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5c692b1a397'
down_revision = '61f93ce4cf3e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('social_facebook', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_instagram', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_x', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_linkedin', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_youtube', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_telegram', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('social_discord', sa.String(length=300), nullable=True))


def downgrade():
    with op.batch_alter_table('platform_config', schema=None) as batch_op:
        batch_op.drop_column('social_discord')
        batch_op.drop_column('social_telegram')
        batch_op.drop_column('social_youtube')
        batch_op.drop_column('social_linkedin')
        batch_op.drop_column('social_x')
        batch_op.drop_column('social_instagram')
        batch_op.drop_column('social_facebook')
