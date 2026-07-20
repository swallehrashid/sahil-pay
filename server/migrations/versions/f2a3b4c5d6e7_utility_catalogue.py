"""Landlord utility catalogue + optional readings/flat amounts (#6, #8)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-06 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


DEFAULT_TYPES = [
    # (name, category, is_metered)
    ("Water",       "current_utility", True),
    ("Electricity", "current_utility", True),
    ("Garbage",     "current_utility", False),
    ("Security",    "current_utility", False),
    ("Rent deposit",     "deposit", False),
    ("Rental balance",   "balance", False),
]


def upgrade():
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
        batch_op.add_column(sa.Column('amount', sa.Numeric(12, 2), nullable=True))
        batch_op.alter_column('utility_item', existing_type=sa.String(length=20),
                              type_=sa.String(length=80), existing_nullable=False)
        batch_op.alter_column('current_reading', existing_type=sa.Numeric(12, 2), nullable=True)
        batch_op.create_index(op.f('ix_utility_readings_utility_type_id'),
                              ['utility_type_id'], unique=False)
        batch_op.create_foreign_key('fk_utility_readings_utility_type', 'landlord_utility_types',
                                    ['utility_type_id'], ['id'])
        batch_op.drop_constraint('ck_utility_readings_current_gte_previous', type_='check')
        batch_op.create_check_constraint(
            'ck_utility_readings_current_gte_previous',
            '(previous_reading IS NULL) OR (current_reading IS NULL) OR (current_reading >= previous_reading)',
        )

    # Seed each existing landlord's default utility catalogue.
    conn = op.get_bind()
    landlord_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM landlords"))]
    for lid in landlord_ids:
        for name, category, is_metered in DEFAULT_TYPES:
            conn.execute(
                sa.text(
                    "INSERT INTO landlord_utility_types "
                    "(landlord_id, name, category, is_metered, is_active, created_at, updated_at) "
                    "VALUES (:lid, :name, :cat, :met, true, NOW(), NOW()) "
                    "ON CONFLICT (landlord_id, name) DO NOTHING"
                ),
                {"lid": lid, "name": name, "cat": category, "met": is_metered},
            )


def downgrade():
    with op.batch_alter_table('utility_readings', schema=None) as batch_op:
        batch_op.drop_constraint('ck_utility_readings_current_gte_previous', type_='check')
        batch_op.create_check_constraint(
            'ck_utility_readings_current_gte_previous',
            '(previous_reading IS NULL) OR (current_reading >= previous_reading)',
        )
        batch_op.drop_constraint('fk_utility_readings_utility_type', type_='foreignkey')
        batch_op.drop_index(op.f('ix_utility_readings_utility_type_id'))
        batch_op.alter_column('current_reading', existing_type=sa.Numeric(12, 2), nullable=False)
        batch_op.alter_column('utility_item', existing_type=sa.String(length=80),
                              type_=sa.String(length=20), existing_nullable=False)
        batch_op.drop_column('amount')
        batch_op.drop_column('utility_type_id')

    op.drop_index(op.f('ix_landlord_utility_types_landlord_id'), table_name='landlord_utility_types')
    op.drop_table('landlord_utility_types')
