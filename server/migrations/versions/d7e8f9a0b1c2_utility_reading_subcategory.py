"""utility reading subcategory (deposit/balance/current)

Adds UtilityReading.subcategory so a reading can bill any of a category's
subcategories, and widens the per-month uniqueness to include subcategory.

Revision ID: d7e8f9a0b1c2
Revises: 5435e6002fe8
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa


revision = "d7e8f9a0b1c2"
down_revision = "5435e6002fe8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "utility_readings",
        sa.Column("subcategory", sa.String(length=10), nullable=False, server_default="current"),
    )
    # Widen uniqueness to include subcategory so a unit can carry e.g. both a
    # Water current and a Water deposit in the same month.
    with op.batch_alter_table("utility_readings") as batch:
        batch.drop_constraint("uq_utility_readings_unit_item_month", type_="unique")
        batch.create_unique_constraint(
            "uq_utility_readings_unit_item_sub_month",
            ["unit_id", "utility_item", "subcategory", "reading_month"],
        )


def downgrade():
    with op.batch_alter_table("utility_readings") as batch:
        batch.drop_constraint("uq_utility_readings_unit_item_sub_month", type_="unique")
        batch.create_unique_constraint(
            "uq_utility_readings_unit_item_month",
            ["unit_id", "utility_item", "reading_month"],
        )
    op.drop_column("utility_readings", "subcategory")
