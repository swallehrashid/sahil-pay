"""Default report "gross" to rent collected, not every income line

Revision ID: y1a1b2c3d4e5
Revises: x1a1b2c3d4e5
Create Date: 2026-08-17

On a property statement, "Gross" is the number an owner reads as "what my block
earned in rent this period". The column defaulted to "all", which adds water,
garbage, security and penalty collections into that figure and overstates rent.

Deposits were already excluded from both bases and stay excluded — held,
refundable money is never income. This changes only whether NON-RENT INCOME is
folded into the headline gross.

The column is NOT NULL with a server default of 'all', so every existing row
reads 'all' whether or not anybody chose it — there is no way to tell a
deliberate preference from an untouched default. Since the default was never
presented as a decision, existing rows are moved to 'rent_only' along with the
default. The Reports screen's gross-basis selector is unchanged, so any landlord
who does want every income shilling in one number can switch back and that
choice then sticks.
"""

from alembic import op
import sqlalchemy as sa


revision = "y1a1b2c3d4e5"
down_revision = "x1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "landlord_settings", "report_gross_basis",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="rent_only",
    )
    op.execute(
        "UPDATE landlord_settings SET report_gross_basis = 'rent_only' "
        "WHERE report_gross_basis = 'all' OR report_gross_basis IS NULL"
    )


def downgrade():
    op.alter_column(
        "landlord_settings", "report_gross_basis",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="all",
    )
    op.execute(
        "UPDATE landlord_settings SET report_gross_basis = 'all' "
        "WHERE report_gross_basis = 'rent_only'"
    )
