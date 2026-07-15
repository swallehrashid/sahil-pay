"""Balance rollover: unique per (source line, origin month) (Phase 3)

A balance line that carries several origin-month components forward needs one
BalanceRollover row per component, so the uniqueness must include origin_month.
This still blocks re-rolling the same source (idempotency). Table is empty at this
point, so the swap is data-safe. See spec §1.4 / §3.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-07 11:00:00.000000

"""
from alembic import op


revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('balance_rollovers', schema=None) as batch_op:
        batch_op.drop_constraint('uq_balance_rollovers_source', type_='unique')
        batch_op.create_unique_constraint(
            'uq_balance_rollovers_source_origin',
            ['source_line_item_id', 'origin_month'],
        )


def downgrade():
    with op.batch_alter_table('balance_rollovers', schema=None) as batch_op:
        batch_op.drop_constraint('uq_balance_rollovers_source_origin', type_='unique')
        batch_op.create_unique_constraint(
            'uq_balance_rollovers_source',
            ['source_line_item_id'],
        )