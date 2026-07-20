"""Affiliate program — referrals, commissions, withdrawals, program config

Purely ADDITIVE. Introduces the affiliates / affiliate_referrals /
affiliate_commissions / affiliate_withdrawals tables, the single-row
affiliate_program_config settings table (seeded with the agreed defaults:
40% / 4 months / KES 500 minimum / 5% WHT / 3% platform fee / 7-day
attribution grace), landlords.referral_code_entered, and the FK columns on
billing_transactions used by the manual-verify/reverse admin flow are
already in place from e05d6bf1008d. See AFFILIATE_PROGRAM_SPEC.md §4.

Revision ID: 3743a24840d5
Revises: e05d6bf1008d
Create Date: 2026-07-07 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3743a24840d5'
down_revision = 'e05d6bf1008d'
branch_labels = None
depends_on = None


def upgrade():
    # 1) landlords.referral_code_entered ---------------------------------------
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.add_column(sa.Column('referral_code_entered', sa.String(length=12), nullable=True))

    # 2) affiliates -------------------------------------------------------------
    op.create_table(
        'affiliates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('mpesa_number', sa.String(length=20), nullable=True),
        sa.Column('national_id', sa.String(length=30), nullable=True),
        sa.Column('kra_pin', sa.String(length=20), nullable=True),
        sa.Column('referral_code', sa.String(length=12), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('commission_rate_override', sa.Numeric(5, 2), nullable=True),
        sa.Column('commission_months_override', sa.Integer(), nullable=True),
        sa.Column('approved_by_admin_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['approved_by_admin_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_affiliates_user'),
        sa.UniqueConstraint('referral_code', name='uq_affiliates_referral_code'),
    )
    op.create_index(op.f('ix_affiliates_user_id'), 'affiliates', ['user_id'], unique=False)
    op.create_index(op.f('ix_affiliates_referral_code'), 'affiliates', ['referral_code'], unique=False)

    # 3) affiliate_referrals -----------------------------------------------------
    op.create_table(
        'affiliate_referrals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('rate', sa.Numeric(5, 2), nullable=False),
        sa.Column('months_total', sa.Integer(), nullable=False),
        sa.Column('months_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('window_started_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='active'),
        sa.Column('attributed_by', sa.String(length=20), nullable=False, server_default='registration'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('landlord_id', name='uq_affiliate_referrals_landlord'),
        sa.CheckConstraint('months_used >= 0 AND months_used <= months_total',
                           name='ck_affiliate_referrals_months_bounds'),
    )
    op.create_index(op.f('ix_affiliate_referrals_affiliate_id'), 'affiliate_referrals', ['affiliate_id'], unique=False)
    op.create_index(op.f('ix_affiliate_referrals_landlord_id'), 'affiliate_referrals', ['landlord_id'], unique=False)

    # 4) affiliate_commissions ---------------------------------------------------
    op.create_table(
        'affiliate_commissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('referral_id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('billing_transaction_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('rate_applied', sa.Numeric(5, 2), nullable=False),
        sa.Column('monthly_equivalent', sa.Numeric(12, 2), nullable=False),
        sa.Column('months_commissioned', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='confirmed'),
        sa.Column('reversed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['referral_id'], ['affiliate_referrals.id'], ),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ),
        sa.ForeignKeyConstraint(['billing_transaction_id'], ['billing_transactions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_affiliate_commissions_referral_id'), 'affiliate_commissions', ['referral_id'], unique=False)
    op.create_index(op.f('ix_affiliate_commissions_affiliate_id'), 'affiliate_commissions', ['affiliate_id'], unique=False)
    op.create_index(op.f('ix_affiliate_commissions_billing_transaction_id'),
                    'affiliate_commissions', ['billing_transaction_id'], unique=False)
    # Idempotency backstop (E10/E16): at most one LIVE commission per billing
    # transaction. A reversed row doesn't block a fresh accrual on a retried txn.
    op.create_index(
        'uq_affiliate_commissions_txn_live',
        'affiliate_commissions',
        ['billing_transaction_id'],
        unique=True,
        postgresql_where=sa.text("status != 'reversed'"),
    )

    # 5) affiliate_withdrawals ----------------------------------------------------
    op.create_table(
        'affiliate_withdrawals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('gross_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('wht_rate', sa.Numeric(5, 2), nullable=False),
        sa.Column('wht_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee_type', sa.String(length=10), nullable=False),
        sa.Column('fee_value', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('net_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='requested'),
        sa.Column('receipt_number', sa.String(length=30), nullable=True),
        sa.Column('mpesa_reference', sa.String(length=50), nullable=True),
        sa.Column('processed_by_admin_id', sa.Integer(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id'], ),
        sa.ForeignKeyConstraint(['processed_by_admin_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('receipt_number', name='uq_affiliate_withdrawals_receipt_number'),
        sa.CheckConstraint('wht_amount + fee_amount + net_amount = gross_amount',
                           name='ck_affiliate_withdrawals_breakdown_sums'),
    )
    op.create_index(op.f('ix_affiliate_withdrawals_affiliate_id'), 'affiliate_withdrawals', ['affiliate_id'], unique=False)

    # 6) affiliate_program_config (single global row) -----------------------------
    op.create_table(
        'affiliate_program_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('default_commission_rate', sa.Numeric(5, 2), nullable=False, server_default='40.00'),
        sa.Column('default_commission_months', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('min_withdrawal', sa.Numeric(12, 2), nullable=False, server_default='500.00'),
        sa.Column('wht_rate', sa.Numeric(5, 2), nullable=False, server_default='5.00'),
        sa.Column('fee_type', sa.String(length=10), nullable=False, server_default='percent'),
        sa.Column('fee_value', sa.Numeric(12, 2), nullable=False, server_default='3.00'),
        sa.Column('attribution_grace_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('is_program_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.execute(
        "INSERT INTO affiliate_program_config "
        "(default_commission_rate, default_commission_months, min_withdrawal, "
        " wht_rate, fee_type, fee_value, attribution_grace_days, is_program_active, "
        " created_at) "
        "VALUES (40.00, 4, 500.00, 5.00, 'percent', 3.00, 7, true, now())"
    )


def downgrade():
    op.drop_table('affiliate_program_config')
    op.drop_index('ix_affiliate_withdrawals_affiliate_id', table_name='affiliate_withdrawals')
    op.drop_table('affiliate_withdrawals')
    op.drop_index('uq_affiliate_commissions_txn_live', table_name='affiliate_commissions')
    op.drop_index(op.f('ix_affiliate_commissions_billing_transaction_id'), table_name='affiliate_commissions')
    op.drop_index(op.f('ix_affiliate_commissions_affiliate_id'), table_name='affiliate_commissions')
    op.drop_index(op.f('ix_affiliate_commissions_referral_id'), table_name='affiliate_commissions')
    op.drop_table('affiliate_commissions')
    op.drop_index(op.f('ix_affiliate_referrals_landlord_id'), table_name='affiliate_referrals')
    op.drop_index(op.f('ix_affiliate_referrals_affiliate_id'), table_name='affiliate_referrals')
    op.drop_table('affiliate_referrals')
    op.drop_index(op.f('ix_affiliates_referral_code'), table_name='affiliates')
    op.drop_index(op.f('ix_affiliates_user_id'), table_name='affiliates')
    op.drop_table('affiliates')
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.drop_column('referral_code_entered')
