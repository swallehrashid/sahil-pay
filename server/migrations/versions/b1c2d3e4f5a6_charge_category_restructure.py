"""Charge-category restructure — foundation schema (Phase 1)

Purely ADDITIVE. Introduces the charge_categories catalogue, the balance_rollovers
audit trail, the credit_ledger, line-item-level allocation columns, tenant credit
balance and the new landlord allocation-priority column. The deprecated
landlord_utility_types table + old columns are left in place and dropped in the
phase that removes their last consumers. See CATEGORY_RESTRUCTURE_SPEC.md §7.

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-07-07 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


# (name, kind, is_metered, auto_bill_monthly) — mirrors services/category_service.py
DEFAULT_CATEGORIES = [
    ("Rent",            "invoice", False, True),
    ("Lease Agreement", "invoice", False, False),
    ("Penalty",         "invoice", False, False),
    ("Water",           "utility", True,  False),
    ("Electricity",     "utility", True,  False),
    ("Security",        "utility", False, False),
]


def upgrade():
    # 1) charge_categories ---------------------------------------------------
    op.create_table(
        'charge_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_metered', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('default_rate', sa.Numeric(12, 2), nullable=True),
        sa.Column('auto_bill_monthly', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('landlord_id', 'name', name='uq_charge_categories_landlord_name'),
        sa.CheckConstraint('NOT (is_metered AND auto_bill_monthly)',
                           name='ck_charge_categories_metered_not_autobill'),
    )
    op.create_index(op.f('ix_charge_categories_landlord_id'),
                    'charge_categories', ['landlord_id'], unique=False)

    # 2) invoice_line_items: category + line-level paid/status ----------------
    with op.batch_alter_table('invoice_line_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('subcategory', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('amount_paid', sa.Numeric(12, 2),
                                      server_default='0', nullable=False))
        batch_op.add_column(sa.Column('status', sa.String(length=10),
                                      server_default='open', nullable=False))
        batch_op.create_index(op.f('ix_invoice_line_items_category_id'),
                              ['category_id'], unique=False)
        batch_op.create_index(op.f('ix_invoice_line_items_subcategory'),
                              ['subcategory'], unique=False)
        batch_op.create_foreign_key('fk_invoice_line_items_category',
                                    'charge_categories', ['category_id'], ['id'])

    # 3) payment_allocations: line-level target -------------------------------
    with op.batch_alter_table('payment_allocations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_item_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_payment_allocations_line_item_id'),
                              ['line_item_id'], unique=False)
        batch_op.create_foreign_key('fk_payment_allocations_line_item',
                                    'invoice_line_items', ['line_item_id'], ['id'])

    # 4) tenants.credit_balance ----------------------------------------------
    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credit_balance', sa.Numeric(12, 2),
                                      server_default='0', nullable=False))

    # 5) landlords.allocation_priority_json ----------------------------------
    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allocation_priority_json', sa.Text(), nullable=True))

    # 6) utility_readings.category_id ----------------------------------------
    with op.batch_alter_table('utility_readings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_utility_readings_category_id'),
                              ['category_id'], unique=False)
        batch_op.create_foreign_key('fk_utility_readings_category',
                                    'charge_categories', ['category_id'], ['id'])

    # 7) balance_rollovers ----------------------------------------------------
    op.create_table(
        'balance_rollovers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('source_line_item_id', sa.Integer(), nullable=False),
        sa.Column('target_line_item_id', sa.Integer(), nullable=False),
        sa.Column('origin_month', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['category_id'], ['charge_categories.id'], ),
        sa.ForeignKeyConstraint(['source_line_item_id'], ['invoice_line_items.id'], ),
        sa.ForeignKeyConstraint(['target_line_item_id'], ['invoice_line_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_line_item_id', name='uq_balance_rollovers_source'),
    )
    op.create_index(op.f('ix_balance_rollovers_landlord_id'),
                    'balance_rollovers', ['landlord_id'], unique=False)
    op.create_index(op.f('ix_balance_rollovers_tenant_id'),
                    'balance_rollovers', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_balance_rollovers_category_id'),
                    'balance_rollovers', ['category_id'], unique=False)
    op.create_index(op.f('ix_balance_rollovers_target_line_item_id'),
                    'balance_rollovers', ['target_line_item_id'], unique=False)

    # 8) credit_ledger --------------------------------------------------------
    op.create_table(
        'credit_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('line_item_id', sa.Integer(), nullable=True),
        sa.Column('memo', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
        sa.ForeignKeyConstraint(['line_item_id'], ['invoice_line_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_credit_ledger_landlord_id'),
                    'credit_ledger', ['landlord_id'], unique=False)
    op.create_index(op.f('ix_credit_ledger_tenant_id'),
                    'credit_ledger', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_credit_ledger_payment_id'),
                    'credit_ledger', ['payment_id'], unique=False)
    op.create_index(op.f('ix_credit_ledger_line_item_id'),
                    'credit_ledger', ['line_item_id'], unique=False)

    # 9) seed each existing landlord's protected default categories -----------
    conn = op.get_bind()
    landlord_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM landlords"))]
    for lid in landlord_ids:
        for name, kind, metered, auto_bill in DEFAULT_CATEGORIES:
            conn.execute(
                sa.text(
                    "INSERT INTO charge_categories "
                    "(landlord_id, name, kind, is_metered, auto_bill_monthly, "
                    " is_default, is_active, created_at, updated_at) "
                    "VALUES (:lid, :name, :kind, :met, :ab, true, true, NOW(), NOW()) "
                    "ON CONFLICT (landlord_id, name) DO NOTHING"
                ),
                {"lid": lid, "name": name, "kind": kind, "met": metered, "ab": auto_bill},
            )


def downgrade():
    op.drop_index(op.f('ix_credit_ledger_line_item_id'), table_name='credit_ledger')
    op.drop_index(op.f('ix_credit_ledger_payment_id'), table_name='credit_ledger')
    op.drop_index(op.f('ix_credit_ledger_tenant_id'), table_name='credit_ledger')
    op.drop_index(op.f('ix_credit_ledger_landlord_id'), table_name='credit_ledger')
    op.drop_table('credit_ledger')

    op.drop_index(op.f('ix_balance_rollovers_target_line_item_id'), table_name='balance_rollovers')
    op.drop_index(op.f('ix_balance_rollovers_category_id'), table_name='balance_rollovers')
    op.drop_index(op.f('ix_balance_rollovers_tenant_id'), table_name='balance_rollovers')
    op.drop_index(op.f('ix_balance_rollovers_landlord_id'), table_name='balance_rollovers')
    op.drop_table('balance_rollovers')

    with op.batch_alter_table('utility_readings', schema=None) as batch_op:
        batch_op.drop_constraint('fk_utility_readings_category', type_='foreignkey')
        batch_op.drop_index(op.f('ix_utility_readings_category_id'))
        batch_op.drop_column('category_id')

    with op.batch_alter_table('landlords', schema=None) as batch_op:
        batch_op.drop_column('allocation_priority_json')

    with op.batch_alter_table('tenants', schema=None) as batch_op:
        batch_op.drop_column('credit_balance')

    with op.batch_alter_table('payment_allocations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_payment_allocations_line_item', type_='foreignkey')
        batch_op.drop_index(op.f('ix_payment_allocations_line_item_id'))
        batch_op.drop_column('line_item_id')

    with op.batch_alter_table('invoice_line_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_invoice_line_items_category', type_='foreignkey')
        batch_op.drop_index(op.f('ix_invoice_line_items_subcategory'))
        batch_op.drop_index(op.f('ix_invoice_line_items_category_id'))
        batch_op.drop_column('status')
        batch_op.drop_column('amount_paid')
        batch_op.drop_column('subcategory')
        batch_op.drop_column('category_id')

    op.drop_index(op.f('ix_charge_categories_landlord_id'), table_name='charge_categories')
    op.drop_table('charge_categories')
