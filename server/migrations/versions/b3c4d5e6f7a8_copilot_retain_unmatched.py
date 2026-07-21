"""Add LandlordSettings.copilot_retain_unmatched (COPILOT_LANDLORD_INBOX_SPEC.md §2.3/§6)

Revision ID: b3c4d5e6f7a8
Revises: a4b5c6d7e8f9
Create Date: 2026-07-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('copilot_retain_unmatched', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.alter_column('copilot_retain_unmatched', server_default=None)


def downgrade():
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.drop_column('copilot_retain_unmatched')
