"""Charges that are ready to bill but have no invoice yet

Revision ID: ad1b2c3d4e5f
Revises: ac1b2c3d4e5f
Create Date: 2026-08-18

Meter readings are taken between the 27th and the 30th; the bill goes out on the
1st. At reading time there is nothing sensible to attach the charge to — last
month's invoice is closing and next month's does not exist yet. Until now the
only choices were to raise a one-line invoice per reading (a second bill the
tenant did not need and did not expect) or to hold the paper until the 1st and
re-key it, which is where readings get lost.

A queued charge waits, and the next invoice for that unit picks it up.

ANCHORED TO THE UNIT rather than the tenant: the water was used by the meter,
and a tenant moving out on the 30th should not carry a reading against a unit
they have left. occupant_at_queue_id snapshots who was there when it was queued
so a change of occupant is visible at billing time instead of being discovered
later.

status + consumed_by_invoice_id are what make consumption exactly-once, which is
what stops a re-run of the monthly billing charging the same reading twice.
"""

from alembic import op
import sqlalchemy as sa


revision = "ad1b2c3d4e5f"
down_revision = "ac1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "queued_charges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("occupant_at_queue_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("subcategory", sa.String(length=10), nullable=True),
        sa.Column("item", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("utility_reading_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="queued", nullable=False),
        sa.Column("consumed_by_invoice_id", sa.Integer(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["occupant_at_queue_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["charge_categories.id"]),
        sa.ForeignKeyConstraint(["utility_reading_id"], ["utility_readings.id"]),
        sa.ForeignKeyConstraint(["consumed_by_invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queued_charges_landlord_id", "queued_charges", ["landlord_id"])
    op.create_index("ix_queued_charges_unit_id", "queued_charges", ["unit_id"])
    op.create_index("ix_queued_charges_status", "queued_charges", ["status"])
    op.create_index("ix_queued_charges_utility_reading_id",
                    "queued_charges", ["utility_reading_id"])
    # The hot path: "what is waiting for this unit?", asked once per unit on
    # every monthly billing run.
    op.create_index("ix_queued_charges_unit_status", "queued_charges",
                    ["unit_id", "status"])


def downgrade():
    op.drop_index("ix_queued_charges_unit_status", table_name="queued_charges")
    op.drop_index("ix_queued_charges_utility_reading_id", table_name="queued_charges")
    op.drop_index("ix_queued_charges_status", table_name="queued_charges")
    op.drop_index("ix_queued_charges_unit_id", table_name="queued_charges")
    op.drop_index("ix_queued_charges_landlord_id", table_name="queued_charges")
    op.drop_table("queued_charges")
