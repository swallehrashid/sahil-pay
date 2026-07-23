"""notifications: add recipient_tenant_id, make recipient_user_id nullable

Revision ID: fd0e10981cd2
Revises: c2b3d4e5f6a7
Create Date: 2026-07-23 00:29:52.042712

Only the notifications table is touched here. The autogenerate run also
surfaced unrelated pre-existing model/DB drift (affiliates unique indexes,
created_at NOT NULLs, etc.) — those are intentionally left out so this
migration is scoped to the tenant-notification feature.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fd0e10981cd2'
down_revision = 'c2b3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipient_tenant_id', sa.Integer(), nullable=True))
        batch_op.alter_column('recipient_user_id',
               existing_type=sa.INTEGER(),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_notifications_recipient_tenant_id'), ['recipient_tenant_id'], unique=False)
        batch_op.create_index('ix_notifications_tenant_is_read', ['recipient_tenant_id', 'is_read'], unique=False)
        batch_op.create_foreign_key(
            'fk_notifications_recipient_tenant_id', 'tenants',
            ['recipient_tenant_id'], ['id'])


def downgrade():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_constraint('fk_notifications_recipient_tenant_id', type_='foreignkey')
        batch_op.drop_index('ix_notifications_tenant_is_read')
        batch_op.drop_index(batch_op.f('ix_notifications_recipient_tenant_id'))
        batch_op.alter_column('recipient_user_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('recipient_tenant_id')
