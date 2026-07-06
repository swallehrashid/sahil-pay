"""Package public storefront fields (featured/recommended/popular + marketing copy)

Revision ID: d3a7b19c4f22
Revises: c8d2e5f10a11
Create Date: 2026-07-04 04:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3a7b19c4f22'
down_revision = 'c8d2e5f10a11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_featured', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('is_recommended', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('is_popular', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('public_description', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('feature_list', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('display_order', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.drop_column('display_order')
        batch_op.drop_column('feature_list')
        batch_op.drop_column('public_description')
        batch_op.drop_column('is_popular')
        batch_op.drop_column('is_recommended')
        batch_op.drop_column('is_featured')
