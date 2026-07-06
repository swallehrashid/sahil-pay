"""SMS reselling: admin pricing config, shared-pool ledger, comm-log analytics columns

Revision ID: c8d2e5f10a11
Revises: b7f1a2c9d3e4
Create Date: 2026-07-04 03:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8d2e5f10a11'
down_revision = 'b7f1a2c9d3e4'
branch_labels = None
depends_on = None


def upgrade():
    # Admin-editable SMS pricing/pool singleton (§9.3).
    op.create_table(
        'sms_pricing_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('default_price_per_sms', sa.Numeric(8, 4), server_default='1.0000', nullable=False),
        sa.Column('custom_price_per_sms', sa.Numeric(8, 4), server_default='0.5000', nullable=False),
        sa.Column('platform_cost_per_sms', sa.Numeric(8, 4), server_default='0.6500', nullable=False),
        sa.Column('pool_balance', sa.Integer(), server_default='0', nullable=False),
        sa.Column('shared_sending_enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # Seed the singleton row (id=1) with the model defaults.
    op.execute(
        "INSERT INTO sms_pricing_config "
        "(id, default_price_per_sms, custom_price_per_sms, platform_cost_per_sms, pool_balance, shared_sending_enabled) "
        "VALUES (1, 1.0000, 0.5000, 0.6500, 0, true)"
    )

    # Append-only ledger of admin pool top-ups.
    op.create_table(
        'sms_pool_topups',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('admin_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('credits_added', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sms_pool_topups_admin_user_id', 'sms_pool_topups', ['admin_user_id'])

    # SMS analytics snapshot columns on communication_logs.
    with op.batch_alter_table('communication_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sms_segments', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('uses_own_sender', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('platform_cost', sa.Numeric(8, 2), server_default='0.00', nullable=False))


def downgrade():
    with op.batch_alter_table('communication_logs', schema=None) as batch_op:
        batch_op.drop_column('platform_cost')
        batch_op.drop_column('uses_own_sender')
        batch_op.drop_column('sms_segments')

    op.drop_index('ix_sms_pool_topups_admin_user_id', table_name='sms_pool_topups')
    op.drop_table('sms_pool_topups')
    op.drop_table('sms_pricing_config')
