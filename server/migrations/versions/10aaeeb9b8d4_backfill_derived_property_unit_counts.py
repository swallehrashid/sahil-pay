"""backfill derived property unit counts

properties.number_of_units was a number somebody typed in once and nothing ever
corrected. Bulk import in particular created every property with it at the
default of 0 and then added the units without coming back — so an account that
imported 100 properties and 1,000 units showed "0 units" against every block,
on screen and in every export.

It is now derived: services/unit_counts.recount() recomputes it from the units
table, and is called on unit create, unit delete, bulk import and tenant
import. This migration corrects the rows that were already wrong when that
landed, so existing accounts are right on the first page load after deploy
rather than only after the next import.

Data only — no schema change. The down migration is a no-op on purpose: the
previous values were not a state worth restoring, they were drift.

Revision ID: 10aaeeb9b8d4
Revises: b4e2546695a4
"""

from alembic import op

revision = "10aaeeb9b8d4"
down_revision = "b4e2546695a4"
branch_labels = None
depends_on = None


def upgrade():
    # One statement, however many properties. Soft-deleted units do not count;
    # a property with none lands on 0 rather than keeping a stale figure.
    op.execute(
        """
        UPDATE properties AS p
        SET number_of_units = COALESCE((
            SELECT COUNT(*) FROM units AS u
            WHERE u.property_id = p.id AND u.is_deleted = false
        ), 0)
        """
    )


def downgrade():
    # Nothing to restore — see the module docstring.
    pass
