"""Send a payment receipt once, not once per code path

Revision ID: w1a1b2c3d4e5
Revises: v1a1b2c3d4e5
Create Date: 2026-08-17

A receipt is a statement of fact about one event, and several places each
decided independently that one was due: recording a payment, co-pilot
auto-allocation, M-Pesa reconciliation, the landlord's "send receipt" button,
and — worst of the set — two GET download endpoints that emailed a fresh copy
every time the PDF was fetched. Nothing recorded that a receipt had already
gone out, so nothing could decline to send a second.

The download side effect made it self-amplifying rather than merely duplicated:
a tenant opening their own receipt got another one by email, and a mail
scanner PREFETCHING the public link (Outlook Safe Links, chat previews)
generated copies with no human involved at all.

This column is the shared record those paths were missing. Existing payments
are backfilled from created_at rather than left NULL: NULL means "never
emailed", and treating the entire payment history as un-receipted would let any
later pass mail thousands of duplicate receipts for payments settled months ago.
"""

from alembic import op
import sqlalchemy as sa


revision = "w1a1b2c3d4e5"
down_revision = "v1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payments",
        sa.Column("receipt_emailed_at", sa.DateTime(), nullable=True),
    )

    # Treat historical confirmed payments as already receipted — see docstring.
    op.execute(
        """
        UPDATE payments
           SET receipt_emailed_at = COALESCE(created_at, NOW())
         WHERE status = 'confirmed'
        """
    )


def downgrade():
    op.drop_column("payments", "receipt_emailed_at")
