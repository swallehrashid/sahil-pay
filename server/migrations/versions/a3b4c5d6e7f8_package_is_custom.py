"""Custom package flag + seed the default Custom package (#17)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-06 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3b4c5d6e7f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_custom', sa.Boolean(), server_default=sa.false(), nullable=False))

    # Seed exactly one Custom package (never featured/recommended/public).
    conn = op.get_bind()
    exists = conn.execute(sa.text("SELECT id FROM packages WHERE is_custom = true LIMIT 1")).first()
    if not exists:
        conn.execute(sa.text(
            "INSERT INTO packages "
            "(name, min_units, max_units, price_per_unit, flat_price, is_active, "
            " is_featured, is_recommended, is_popular, is_custom, display_order, created_at, updated_at) "
            "VALUES ('Custom', 1, NULL, 0, NULL, true, false, false, false, true, 999, NOW(), NOW())"
        ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM packages WHERE is_custom = true"))
    with op.batch_alter_table('packages', schema=None) as batch_op:
        batch_op.drop_column('is_custom')
