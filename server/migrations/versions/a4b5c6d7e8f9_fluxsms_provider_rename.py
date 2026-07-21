"""FluxSMS provider rename — landlord_settings at_* -> sms_* (drop at_username)

Revision ID: a4b5c6d7e8f9
Revises: 70d7e5498282
Create Date: 2026-07-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = '70d7e5498282'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.alter_column('at_api_key', new_column_name='sms_api_key')
        batch_op.alter_column('at_sender_id', new_column_name='sms_sender_id')
        batch_op.alter_column('at_connected', new_column_name='sms_connected')
        batch_op.drop_column('at_username')


def downgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('at_username', sa.String(length=120), nullable=True))
        batch_op.alter_column('sms_connected', new_column_name='at_connected')
        batch_op.alter_column('sms_sender_id', new_column_name='at_sender_id')
        batch_op.alter_column('sms_api_key', new_column_name='at_api_key')
