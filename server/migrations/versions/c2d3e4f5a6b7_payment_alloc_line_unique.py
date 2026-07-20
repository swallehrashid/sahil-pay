"""Payment allocation: swap unique constraint to line-item level (Phase 2)

The allocation engine now writes one PaymentAllocation per invoice LINE ITEM, so a
single payment can clear several lines of the same invoice. Replace the old
(payment_id, invoice_id) uniqueness with (payment_id, line_item_id). line_item_id
stays nullable for now (old invoice-level rows carry NULL and are re-seeded later;
Postgres treats NULLs as distinct so they don't collide). See spec §1.3.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-07 10:00:00.000000

"""
from alembic import op


revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payment_allocations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_payment_allocations_payment_invoice', type_='unique')
        batch_op.create_unique_constraint(
            'uq_payment_allocations_payment_line_item',
            ['payment_id', 'line_item_id'],
        )


def downgrade():
    with op.batch_alter_table('payment_allocations', schema=None) as batch_op:
        batch_op.drop_constraint('uq_payment_allocations_payment_line_item', type_='unique')
        batch_op.create_unique_constraint(
            'uq_payment_allocations_payment_invoice',
            ['payment_id', 'invoice_id'],
        )
