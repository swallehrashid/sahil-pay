"""Say why a message failed instead of only that it did

Revision ID: ag1b2c3d4e5f
Revises: af1b2c3d4e5f
Create Date: 2026-08-18

A blocked send was recorded as status='failed' and nothing else, and the send
endpoint still answered "N message(s) dispatched" — so the screen showed a green
"Sent to 1 recipient" over a log full of red Failed rows, with no cause given
anywhere. The reasons are known at the moment of failure and are all actionable
by different people:

  * the platform SMS pool is exhausted        → an administrator tops it up
  * the shared sender is switched off         → an administrator re-enables it
  * the landlord's own credits ran out        → the landlord buys credits
  * no phone number / email on the tenancy    → the office fixes the record
  * the provider rejected it                  → the sender ID needs approval

Nullable, no backfill: an existing failed row's reason is genuinely unknown, and
inventing one would be worse than leaving it blank.
"""

from alembic import op
import sqlalchemy as sa


revision = "ag1b2c3d4e5f"
down_revision = "af1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("communication_logs",
                  sa.Column("failure_reason", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("communication_logs", "failure_reason")
