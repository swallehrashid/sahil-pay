"""Add demo mode fields to landlords (DEMO_MODE_SPEC.md §2)

Revision ID: a7b8c9d0e1f2
Revises: f8a9b0c1d2e3
Create Date: 2026-07-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7b8c9d0e1f2'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('demo_owner_landlord_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('demo_created_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('demo_last_reset_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_landlords_is_demo', ['is_demo'])
        batch_op.create_index('ix_landlords_demo_owner_landlord_id', ['demo_owner_landlord_id'], unique=True)
        batch_op.create_foreign_key(
            'fk_landlords_demo_owner_landlord_id', 'landlords',
            ['demo_owner_landlord_id'], ['id'],
        )
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.alter_column('is_demo', server_default=None)


def downgrade():
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.drop_constraint('fk_landlords_demo_owner_landlord_id', type_='foreignkey')
        batch_op.drop_index('ix_landlords_demo_owner_landlord_id')
        batch_op.drop_index('ix_landlords_is_demo')
        batch_op.drop_column('demo_last_reset_at')
        batch_op.drop_column('demo_created_at')
        batch_op.drop_column('demo_owner_landlord_id')
        batch_op.drop_column('is_demo')
