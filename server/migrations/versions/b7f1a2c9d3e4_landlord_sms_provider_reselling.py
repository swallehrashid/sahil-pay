"""landlord Africa's Talking SMS reselling fields on landlord_settings

Revision ID: b7f1a2c9d3e4
Revises: 75c4fa4e146b
Create Date: 2026-07-04 00:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f1a2c9d3e4'
down_revision = '75c4fa4e146b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('at_api_key', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('at_username', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('at_sender_id', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('at_connected', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.drop_column('at_connected')
        batch_op.drop_column('at_sender_id')
        batch_op.drop_column('at_username')
        batch_op.drop_column('at_api_key')
