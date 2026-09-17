"""brand contacts, subscription balance ledger, lease documents and scans

Three features that share one deploy:

1. DOCUMENT IDENTITY — landlords.letterhead_url / contact_phone / contact_email /
   website. Every receipt, report, lease and email a landlord issues carries
   their theme colours, logo, letterhead and contact details.

2. INSTALLMENTS — subscriptions.amount_due becomes a running balance, plus
   balance_due_since (when the oldest unpaid charge fell due) and an admin
   access override.

   Data: amount_due used to be refilled with the plan price whenever it read
   zero, so almost every account shows "owing" one month's price that was never
   actually charged. Where that figure is just the price of a billing date that
   has NOT arrived yet, it is reset to 0 — the charge is added for real when the
   date passes. Trial accounts owe nothing. Anything else is kept.
   balance_due_since starts NULL for everyone, so NOBODY is locked by this
   deploy: the nightly sweep starts a grace clock for a real balance from the
   day it first sees it.

3. LEASES — which document was sent (standard / custom / uploaded), the
   landlord's original file, how the tenant signed, the pages of a hand-signed
   copy, and when the tenant first opened it.

Revision ID: ah1b2c3d4e5f
Revises: 10aaeeb9b8d4
"""

import sqlalchemy as sa
from alembic import op

revision = "ah1b2c3d4e5f"
down_revision = "10aaeeb9b8d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("landlords") as batch:
        batch.add_column(sa.Column("letterhead_url", sa.String(255), nullable=True))
        batch.add_column(sa.Column("contact_phone", sa.String(30), nullable=True))
        batch.add_column(sa.Column("contact_email", sa.String(255), nullable=True))
        batch.add_column(sa.Column("website", sa.String(255), nullable=True))

    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(sa.Column("balance_due_since", sa.Date(), nullable=True))
        batch.add_column(sa.Column("access_override_until", sa.Date(), nullable=True))
        batch.add_column(sa.Column("access_override_reason", sa.String(255), nullable=True))
        batch.add_column(sa.Column("access_override_by", sa.Integer(),
                                   sa.ForeignKey("users.id"), nullable=True))

    op.execute("UPDATE subscriptions SET amount_due = 0 WHERE status = 'trial'")
    op.execute(
        """
        UPDATE subscriptions
        SET amount_due = 0
        WHERE status <> 'trial'
          AND amount_due = subscription_cost
          AND next_billing_date IS NOT NULL
          AND next_billing_date > CURRENT_DATE
        """
    )

    with op.batch_alter_table("lease_agreements") as batch:
        batch.add_column(sa.Column("document_kind", sa.String(10), nullable=False,
                                   server_default="standard"))
        batch.add_column(sa.Column("source_document_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("title", sa.String(150), nullable=True))
        batch.add_column(sa.Column("signing_method", sa.String(10), nullable=True))
        batch.add_column(sa.Column("tenant_scan_urls", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("viewed_at", sa.DateTime(), nullable=True))

    # Leases created from a written template were custom; everything else that
    # went through the portal used the standard agreement.
    op.execute(
        "UPDATE lease_agreements SET document_kind = 'custom' "
        "WHERE template_id IS NOT NULL"
    )
    op.execute(
        "UPDATE lease_agreements SET signing_method = 'electronic' "
        "WHERE signed_name IS NOT NULL"
    )


def downgrade():
    with op.batch_alter_table("lease_agreements") as batch:
        for col in ("viewed_at", "tenant_scan_urls", "signing_method", "title",
                    "source_document_url", "document_kind"):
            batch.drop_column(col)
    with op.batch_alter_table("subscriptions") as batch:
        for col in ("access_override_by", "access_override_reason",
                    "access_override_until", "balance_due_since"):
            batch.drop_column(col)
    with op.batch_alter_table("landlords") as batch:
        for col in ("website", "contact_email", "contact_phone", "letterhead_url"):
            batch.drop_column(col)
