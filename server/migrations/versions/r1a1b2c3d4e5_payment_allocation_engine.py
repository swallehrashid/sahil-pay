"""Payment allocation, commission rules and the payout ledger

sahilpay_payment_allocation_spec.md §5. Additive throughout — every new column
is nullable or carries a server default that reproduces today's behaviour, so
the live schema stays intact and no existing row changes meaning.

  1. unit_pay_code_aliases   — retired pay-codes still resolve
  2. payment_sources         — multi-paybill landlords (resolver layer 0)
  3. commission_rules        — landlord / property / unit, most specific wins
  4. allocation_audit        — every allocate / reallocate / reverse
  5. payout_lines            — per-unit breakdown behind a payout
  6. units.pay_code          — UNIQUE per account, backfilled for every unit
  7. payments.*              — reference_text, source_id, payer_phone,
                               suspense_reason, suggested_split_json
  8. payment_allocations.*   — allocated_by, method
  9. landlords.*             — allocation_method, tax_withholding_enabled
 10. owner_payouts.*         — the settlement ledger columns

BACKFILL NOTES
  * Existing accounts are set to allocation_method='phone' so their behaviour
    is byte-identical to today. The model default for NEW accounts is
    'unit_code'. This is the one place the two deliberately disagree.
  * Every existing unit gets a generated pay_code. Uniqueness is per ACCOUNT
    (a PM's single paybill receives for every block), enforced by a partial
    unique index that ignores NULLs.

Revision ID: r1a1b2c3d4e5
Revises: q1a1b2c3d4e5
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "r1a1b2c3d4e5"
down_revision = "q1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    # --- 1. unit_pay_code_aliases ------------------------------------------
    op.create_table(
        "unit_pay_code_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("old_code", sa.String(length=30), nullable=False),
        sa.Column("retired_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("landlord_id", "old_code",
                            name="uq_unit_pay_code_aliases_landlord_code"),
    )
    op.create_index("ix_unit_pay_code_aliases_unit_id", "unit_pay_code_aliases", ["unit_id"])
    op.create_index("ix_unit_pay_code_aliases_landlord_id", "unit_pay_code_aliases", ["landlord_id"])
    op.create_index("ix_unit_pay_code_aliases_old_code", "unit_pay_code_aliases", ["old_code"])

    # --- 2. payment_sources -------------------------------------------------
    op.create_table(
        "payment_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("shortcode", sa.String(length=30), nullable=True),
        sa.Column("match_pattern", sa.String(length=120), nullable=True),
        sa.Column("mapped_property_id", sa.Integer(), nullable=True),
        sa.Column("mapped_owner_id", sa.Integer(), nullable=True),
        sa.Column("forwarding_phone", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["mapped_property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["mapped_owner_id"], ["property_owners.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("landlord_id", "shortcode",
                            name="uq_payment_sources_landlord_shortcode"),
    )
    op.create_index("ix_payment_sources_landlord_id", "payment_sources", ["landlord_id"])
    op.create_index("ix_payment_sources_shortcode", "payment_sources", ["shortcode"])
    op.create_index("ix_payment_sources_mapped_property_id", "payment_sources",
                    ["mapped_property_id"])
    op.create_index("ix_payment_sources_mapped_owner_id", "payment_sources",
                    ["mapped_owner_id"])

    # --- 3. commission_rules ------------------------------------------------
    op.create_table(
        "commission_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=10), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("rate_type", sa.String(length=12), nullable=False,
                  server_default="percentage"),
        sa.Column("rate_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("landlord_id", "scope_type", "scope_id",
                            name="uq_commission_rules_scope"),
        sa.CheckConstraint("rate_value >= 0", name="ck_commission_rules_non_negative"),
    )
    op.create_index("ix_commission_rules_landlord_id", "commission_rules", ["landlord_id"])
    op.create_index("ix_commission_rules_lookup", "commission_rules",
                    ["landlord_id", "scope_type", "scope_id"])

    # --- 4. allocation_audit ------------------------------------------------
    op.create_table(
        "allocation_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("before_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_allocation_audit_landlord_id", "allocation_audit", ["landlord_id"])
    op.create_index("ix_allocation_audit_payment_id", "allocation_audit", ["payment_id"])

    # --- 5. payout_lines ----------------------------------------------------
    op.create_table(
        "payout_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payout_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("rent_collected", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("deposits_collected", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("other_collected", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["payout_id"], ["owner_payouts.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payout_lines_payout_id", "payout_lines", ["payout_id"])
    op.create_index("ix_payout_lines_unit_id", "payout_lines", ["unit_id"])
    op.create_index("ix_payout_lines_tenant_id", "payout_lines", ["tenant_id"])

    # --- 6. units.pay_code + denormalised landlord_id ----------------------
    # landlord_id is denormalised onto units ONLY so account-wide pay-code
    # uniqueness can be a real constraint: Postgres cannot put a subquery in an
    # index expression, and per-property uniqueness would still let a PM's one
    # paybill receive an ambiguous "A1" from two different blocks.
    op.add_column("units", sa.Column("pay_code", sa.String(length=30), nullable=True))
    op.add_column("units", sa.Column("landlord_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_units_landlord_id", "units", "landlords",
                          ["landlord_id"], ["id"])
    op.create_index("ix_units_pay_code", "units", ["pay_code"])
    op.create_index("ix_units_landlord_id", "units", ["landlord_id"])
    op.execute(
        "UPDATE units u SET landlord_id = p.landlord_id "
        "  FROM properties p WHERE p.id = u.property_id"
    )

    # Backfill: {first 2 letters of the property name, uppercased}-{unit id}.
    # The unit id guarantees account-wide uniqueness without a second pass, and
    # owners can rename these to anything they like afterwards.
    op.execute(
        """
        UPDATE units u
           SET pay_code = UPPER(
                   COALESCE(NULLIF(regexp_replace(substring(p.name from 1 for 2),
                                                  '[^A-Za-z0-9]', '', 'g'), ''), 'U')
               ) || '-' || u.id::text
          FROM properties p
         WHERE p.id = u.property_id
           AND u.pay_code IS NULL
        """
    )
    # Partial unique: uniqueness is per ACCOUNT, and units reach their account
    # through properties, so this is enforced on a derived expression rather
    # than a plain column pair. Kept partial so future NULLs never collide.
    op.create_index(
        "uq_units_account_pay_code", "units", ["landlord_id", "pay_code"], unique=True,
        postgresql_where=sa.text("pay_code IS NOT NULL AND is_deleted = false"),
    )

    # --- 7. payments resolver fields ---------------------------------------
    op.add_column("payments", sa.Column("reference_text", sa.String(length=120), nullable=True))
    op.add_column("payments", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("payments", sa.Column("payer_phone", sa.String(length=30), nullable=True))
    op.add_column("payments", sa.Column("suspense_reason", sa.String(length=30), nullable=True))
    op.add_column("payments", sa.Column("suggested_split_json",
                                        postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key("fk_payments_source_id", "payments", "payment_sources",
                          ["source_id"], ["id"])
    op.create_index("ix_payments_reference_text", "payments", ["reference_text"])
    op.create_index("ix_payments_source_id", "payments", ["source_id"])
    # The review queue is "everything not yet settled for this account", so it
    # reads status + landlord together.
    op.create_index("ix_payments_landlord_status", "payments", ["landlord_id", "status"])

    # --- 8. payment_allocations provenance ---------------------------------
    op.add_column("payment_allocations", sa.Column("allocated_by", sa.Integer(), nullable=True))
    op.add_column("payment_allocations", sa.Column("method", sa.String(length=10), nullable=True))
    op.create_foreign_key("fk_payment_allocations_allocated_by", "payment_allocations",
                          "users", ["allocated_by"], ["id"])
    # Everything that already exists was written by the pre-resolver auto path.
    op.execute("UPDATE payment_allocations SET method = 'auto' WHERE method IS NULL")

    # --- 9. landlords: allocation method + withholding ---------------------
    op.add_column("landlords", sa.Column("allocation_method", sa.String(length=12),
                                         nullable=False, server_default="unit_code"))
    op.add_column("landlords", sa.Column("tax_withholding_enabled", sa.Boolean(),
                                         nullable=False, server_default=sa.false()))
    # EXISTING accounts keep today's behaviour; only new ones get unit_code.
    op.execute("UPDATE landlords SET allocation_method = 'phone'")

    # --- 10. owner_payouts settlement ledger -------------------------------
    for column in (
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("total_collected", sa.Numeric(12, 2), nullable=True),
        sa.Column("rent_collected_base", sa.Numeric(12, 2), nullable=True),
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("tax_withheld", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("other_deductions", sa.Numeric(12, 2), nullable=True),
        sa.Column("net_payable", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
    ):
        op.add_column("owner_payouts", column)
    op.create_foreign_key("fk_owner_payouts_owner_id", "owner_payouts",
                          "property_owners", ["owner_id"], ["id"])
    op.create_index("ix_owner_payouts_owner_id", "owner_payouts", ["owner_id"])
    # A payout that already exists was recorded because the money went out.
    op.execute("UPDATE owner_payouts SET status = 'paid' WHERE status IS NULL")
    # Adopt the owner rows the eTIMS migration derived from properties.
    op.execute(
        """
        UPDATE owner_payouts op
           SET owner_id = p.owner_id
          FROM properties p
         WHERE p.id = op.property_id
           AND p.owner_id IS NOT NULL
        """
    )

    # Seed a commission rule per property that already carries a rate, so the
    # three-level engine starts out agreeing exactly with the old single field.
    op.execute(
        """
        INSERT INTO commission_rules (landlord_id, scope_type, scope_id, rate_type,
                                      rate_value, is_active, notes, created_at, updated_at)
        SELECT p.landlord_id, 'property', p.id, 'percentage', p.commission_rate, TRUE,
               'Migrated from properties.commission_rate', NOW(), NOW()
          FROM properties p
         WHERE p.commission_rate IS NOT NULL
           AND p.commission_rate > 0
           AND p.is_deleted = FALSE
        ON CONFLICT ON CONSTRAINT uq_commission_rules_scope DO NOTHING
        """
    )


def downgrade():
    op.drop_index("ix_owner_payouts_owner_id", table_name="owner_payouts")
    op.drop_constraint("fk_owner_payouts_owner_id", "owner_payouts", type_="foreignkey")
    for name in ("owner_id", "paid_at", "status", "net_payable", "other_deductions",
                 "tax_withheld", "tax_amount", "commission_amount",
                 "rent_collected_base", "total_collected", "period_end", "period_start"):
        op.drop_column("owner_payouts", name)

    op.drop_column("landlords", "tax_withholding_enabled")
    op.drop_column("landlords", "allocation_method")

    op.drop_constraint("fk_payment_allocations_allocated_by", "payment_allocations",
                       type_="foreignkey")
    op.drop_column("payment_allocations", "method")
    op.drop_column("payment_allocations", "allocated_by")

    op.drop_index("ix_payments_landlord_status", table_name="payments")
    op.drop_index("ix_payments_source_id", table_name="payments")
    op.drop_index("ix_payments_reference_text", table_name="payments")
    op.drop_constraint("fk_payments_source_id", "payments", type_="foreignkey")
    for name in ("suggested_split_json", "suspense_reason", "payer_phone",
                 "source_id", "reference_text"):
        op.drop_column("payments", name)

    op.drop_index("uq_units_account_pay_code", table_name="units")
    op.drop_index("ix_units_landlord_id", table_name="units")
    op.drop_index("ix_units_pay_code", table_name="units")
    op.drop_constraint("fk_units_landlord_id", "units", type_="foreignkey")
    op.drop_column("units", "landlord_id")
    op.drop_column("units", "pay_code")

    op.drop_table("payout_lines")
    op.drop_table("allocation_audit")
    op.drop_table("commission_rules")
    op.drop_table("payment_sources")
    op.drop_table("unit_pay_code_aliases")
