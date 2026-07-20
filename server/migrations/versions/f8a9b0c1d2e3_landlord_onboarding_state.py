"""Add landlords.onboarding_state_json (ONBOARDING_TUTORIALS_SPEC.md §4.1)

Revision ID: f8a9b0c1d2e3
Revises: 5789a1551068
Create Date: 2026-07-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f8a9b0c1d2e3'
down_revision = '5789a1551068'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.add_column(sa.Column('onboarding_state_json', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.drop_column('onboarding_state_json')
