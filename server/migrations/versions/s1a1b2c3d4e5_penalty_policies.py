"""Late-payment penalties — per-property policies, balance tiers, charge ledger

Revision ID: s1a1b2c3d4e5
Revises: r1a1b2c3d4e5
Create Date: 2026-08-13

Penalties were previously a single per-property amount with a manual task and
no scheduling. This adds the policy, the banded amounts, and an append-only
charge ledger whose partial unique index is what actually guarantees a tenant
is auto-charged at most once per month.

The legacy `properties.rent_payment_penalty` / `tenants.rent_payment_penalty`
columns are left in place and back-filled into the new policy as a `fixed`
amount, so nothing an owner already configured is lost.
"""

from alembic import op
import sqlalchemy as sa


revision = "s1a1b2c3d4e5"
down_revision = "r1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "property_penalty_policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mode", sa.String(length=12), server_default="fixed", nullable=False),
        sa.Column("fixed_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("percentage_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("trigger_type", sa.String(length=16), server_default="day_of_month", nullable=False),
        sa.Column("trigger_day", sa.Integer(), nullable=True),
        sa.Column("grace_days", sa.Integer(), nullable=True),
        sa.Column("min_balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_penalty", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_id", name="uq_penalty_policy_property"),
        sa.CheckConstraint("fixed_amount IS NULL OR fixed_amount >= 0",
                           name="ck_penalty_policy_fixed_non_negative"),
        sa.CheckConstraint("percentage_rate IS NULL OR (percentage_rate >= 0 AND percentage_rate <= 100)",
                           name="ck_penalty_policy_rate_range"),
        sa.CheckConstraint("trigger_day IS NULL OR (trigger_day >= 1 AND trigger_day <= 28)",
                           name="ck_penalty_policy_trigger_day"),
        sa.CheckConstraint("grace_days IS NULL OR grace_days >= 0",
                           name="ck_penalty_policy_grace_days"),
    )
    op.create_index("ix_property_penalty_policies_landlord_id",
                    "property_penalty_policies", ["landlord_id"])

    op.create_table(
        "penalty_tiers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("min_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("amount_type", sa.String(length=12), server_default="fixed", nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["policy_id"], ["property_penalty_policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("min_balance >= 0", name="ck_penalty_tier_min_non_negative"),
        sa.CheckConstraint("max_balance IS NULL OR max_balance > min_balance",
                           name="ck_penalty_tier_band_ordered"),
        sa.CheckConstraint("amount >= 0", name="ck_penalty_tier_amount_non_negative"),
    )
    op.create_index("ix_penalty_tiers_policy_id", "penalty_tiers", ["policy_id"])

    op.create_table(
        "penalty_charges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=10), server_default="auto", nullable=False),
        sa.Column("basis_balance", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["property_penalty_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount >= 0", name="ck_penalty_charge_amount_non_negative"),
        sa.CheckConstraint("period_month >= 1 AND period_month <= 12",
                           name="ck_penalty_charge_month_range"),
    )
    for col in ("landlord_id", "property_id", "unit_id", "tenant_id", "invoice_id", "policy_id"):
        op.create_index(f"ix_penalty_charges_{col}", "penalty_charges", [col])
    op.create_index("ix_penalty_charges_report", "penalty_charges",
                    ["landlord_id", "period_year", "period_month"])

    # The once-per-month guarantee. Partial so manual top-ups stay possible:
    # a person adding a second charge is a decision, not a duplicate.
    op.create_index(
        "uq_penalty_charge_auto_per_month", "penalty_charges",
        ["tenant_id", "period_year", "period_month"],
        unique=True, postgresql_where=sa.text("source = 'auto'"),
    )

    # Carry forward whatever owners already configured, switched OFF. Enabling
    # automation is a decision with financial consequences for tenants, so it
    # is never made on someone's behalf by a migration.
    op.execute("""
        INSERT INTO property_penalty_policies
            (landlord_id, property_id, is_enabled, mode, fixed_amount,
             trigger_type, trigger_day, created_at)
        SELECT p.landlord_id, p.id, false, 'fixed', p.rent_payment_penalty,
               'day_of_month', 5, now()
        FROM properties p
        WHERE p.rent_payment_penalty IS NOT NULL
          AND p.rent_payment_penalty > 0
          AND p.is_deleted = false
    """)


def downgrade():
    op.drop_index("uq_penalty_charge_auto_per_month", table_name="penalty_charges")
    op.drop_index("ix_penalty_charges_report", table_name="penalty_charges")
    for col in ("landlord_id", "property_id", "unit_id", "tenant_id", "invoice_id", "policy_id"):
        op.drop_index(f"ix_penalty_charges_{col}", table_name="penalty_charges")
    op.drop_table("penalty_charges")

    op.drop_index("ix_penalty_tiers_policy_id", table_name="penalty_tiers")
    op.drop_table("penalty_tiers")

    op.drop_index("ix_property_penalty_policies_landlord_id",
                  table_name="property_penalty_policies")
    op.drop_table("property_penalty_policies")
