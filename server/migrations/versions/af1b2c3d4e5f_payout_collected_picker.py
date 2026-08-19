"""Record what a payout run counted as collected, and what it commissioned

Revision ID: af1b2c3d4e5f
Revises: ae1b2c3d4e5f
Create Date: 2026-08-18

"Collected" was every shilling that arrived in the period. That is arithmetic,
not a policy: a managing agent does not necessarily remit the water float, the
deposit, or a penalty they keep, and which of those belongs on an owner's
statement is a commercial arrangement. The run now takes an explicit set of
charge types, and a choice of whether commission is charged on rent alone
(the default, and ordinary Kenyan practice) or on the whole included total.

Both are properties of the RUN, so they are stored on the payout. Six months
later "why is this commission different from that one?" must be answerable from
the row, not from whoever remembers which boxes were ticked.

  included_categories  the charge-type keys counted, e.g. ["rent", "deposit",
                       "cat:4"]. NULL = every type, the old behaviour.
  commission_basis     'rent' | 'collected'. NULL reads as 'rent'.
  commission_base      what commission was actually applied to. NULL reads as
                       rent_collected_base, which is what it was.

All three are nullable with no backfill, deliberately: an existing payout was
generated under the old rule, and writing values into it would assert a decision
nobody made. The reader (models.OwnerPayout.to_dict) resolves NULL to the old
behaviour, so historical statements render exactly as they always did.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "af1b2c3d4e5f"
down_revision = "ae1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("owner_payouts",
                  sa.Column("included_categories", postgresql.JSON(astext_type=sa.Text()),
                            nullable=True))
    op.add_column("owner_payouts",
                  sa.Column("commission_basis", sa.String(length=10), nullable=True))
    op.add_column("owner_payouts",
                  sa.Column("commission_base", sa.Numeric(12, 2), nullable=True))


def downgrade():
    op.drop_column("owner_payouts", "commission_base")
    op.drop_column("owner_payouts", "commission_basis")
    op.drop_column("owner_payouts", "included_categories")
