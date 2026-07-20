"""Drop the deprecated landlord_utility_types catalogue (cleanup)

The landlord utility catalogue is now the unified `charge_categories` table. Remove
the old `landlord_utility_types` table and the `utility_readings.utility_type_id`
column that referenced it (readings now use `category_id`).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('utility_readings', schema=None) as batch_op:
        batch_op.drop_constraint('fk_utility_readings_utility_type', type_='foreignkey')
        batch_op.drop_index(op.f('ix_utility_readings_utility_type_id'))
        batch_op.drop_column('utility_type_id')

    op.drop_index(op.f('ix_landlord_utility_types_landlord_id'), table_name='landlord_utility_types')
    op.drop_table('landlord_utility_types')


def downgrade():
    op.create_table(
        'landlord_utility_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('is_metered', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('default_rate', sa.Numeric(12, 2), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('landlord_id', 'name', name='uq_landlord_utility_types_landlord_name'),
    )
    op.create_index(op.f('ix_landlord_utility_types_landlord_id'),
                    'landlord_utility_types', ['landlord_id'], unique=False)

    with op.batch_alter_table('utility_readings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('utility_type_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_utility_readings_utility_type_id'),
                              ['utility_type_id'], unique=False)
        batch_op.create_foreign_key('fk_utility_readings_utility_type',
                                    'landlord_utility_types', ['utility_type_id'], ['id'])
