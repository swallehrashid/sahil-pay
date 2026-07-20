"""Make audit_logs.actor_user_id nullable (tenant self-service actions have no User)

Revision ID: e1f2a3b4c5d6
Revises: d3a7b19c4f22
Create Date: 2026-07-06 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'd3a7b19c4f22'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.alter_column('actor_user_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.alter_column('actor_user_id', existing_type=sa.Integer(), nullable=False)
