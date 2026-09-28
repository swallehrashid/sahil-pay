"""next of kin on tenants, billing month on invoice lines

1. NEXT OF KIN — tenants gain next_of_kin_name / _relationship / _phone. All
   nullable: nobody already on the books is forced to have one.

2. BILLING MONTH — invoice_line_items.period_month (first day of the month the
   charge is FOR). NULL means "derive it" (services/line_period.py): a meter
   reading's month, a carried balance's origin months, else the invoice month.
   It is written explicitly only where the invoice date and the month billed
   differ — a tenant who moves in on the 28th and pays next month's rent up
   front — so that receipt can say "Rent — October" on a September invoice, and
   October's billing run can see October's rent is already billed.

Revision ID: aj1b2c3d4e5f
Revises: ai1b2c3d4e5f
"""

import sqlalchemy as sa
from alembic import op

revision = "aj1b2c3d4e5f"
down_revision = "ai1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("next_of_kin_name", sa.String(150), nullable=True))
    op.add_column("tenants", sa.Column("next_of_kin_relationship", sa.String(60), nullable=True))
    op.add_column("tenants", sa.Column("next_of_kin_phone", sa.String(20), nullable=True))
    op.add_column("invoice_line_items", sa.Column("period_month", sa.Date(), nullable=True))
    op.create_index("ix_invoice_line_items_period_month", "invoice_line_items", ["period_month"])


def downgrade():
    op.drop_index("ix_invoice_line_items_period_month", table_name="invoice_line_items")
    op.drop_column("invoice_line_items", "period_month")
    op.drop_column("tenants", "next_of_kin_phone")
    op.drop_column("tenants", "next_of_kin_relationship")
    op.drop_column("tenants", "next_of_kin_name")
