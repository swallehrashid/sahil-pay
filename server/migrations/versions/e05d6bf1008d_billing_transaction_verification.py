"""Billing transaction verification + reversal columns

Prerequisite for the affiliate program (AFFILIATE_PROGRAM_SPEC.md §3):
a subscription BillingTransaction only becomes commissionable once
is_verified=True (Daraja callback confirmation or explicit admin verify).
Purely additive.

Revision ID: e05d6bf1008d
Revises: e4f5a6b7c8d9
Create Date: 2026-07-07 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e05d6bf1008d'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('billing_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('context_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('is_verified', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('verified_by_admin_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('is_reversed', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('reversed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reversed_by_admin_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reversal_reason', sa.String(length=255), nullable=True))
        batch_op.create_foreign_key('fk_billing_transactions_verified_by',
                                    'users', ['verified_by_admin_id'], ['id'])
        batch_op.create_foreign_key('fk_billing_transactions_reversed_by',
                                    'users', ['reversed_by_admin_id'], ['id'])


def downgrade():
    with op.batch_alter_table('billing_transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_billing_transactions_reversed_by', type_='foreignkey')
        batch_op.drop_constraint('fk_billing_transactions_verified_by', type_='foreignkey')
        batch_op.drop_column('reversal_reason')
        batch_op.drop_column('reversed_by_admin_id')
        batch_op.drop_column('reversed_at')
        batch_op.drop_column('is_reversed')
        batch_op.drop_column('verified_by_admin_id')
        batch_op.drop_column('verified_at')
        batch_op.drop_column('is_verified')
        batch_op.drop_column('context_json')
