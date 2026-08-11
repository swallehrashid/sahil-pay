"""eTIMS / KRA compliance layer + Help Content CMS

SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §1. Entirely additive and entirely
optional: every column added here is nullable or defaults to the value that
reproduces today's behaviour exactly, so an account that never touches the
feature sees no change anywhere — no new columns on documents, no badges, no
empty states.

  1. property_owners            — the human who OWNS a block, as distinct from
                                  the SahilPay account holder. A PM's account
                                  is one Landlord row but a hundred owners, and
                                  it is the owner who is the seller on rent
                                  invoices and the taxpayer on the MRI return.
                                  Backfilled from properties.owner_phone.
  2. KRA PIN columns            — users.kra_pin, properties.kra_pin.
                                  tenants.kra_pin already existed.
  3. Per-property eTIMS opt-in  — properties.etims_enabled (default FALSE) and
                                  properties.etims_display_settings.
  4. eTIMS invoice group        — on payments (landlord→tenant), owner_payouts
                                  (PM→owner commission) and billing_transactions
                                  (SahilPay→client), each with a PARTIAL unique
                                  index on the invoice number.
  5. team_member_property_permissions — per-property `manage_tax_compliance`.
  6. Help Content CMS           — tutorial_categories / _articles / _images.
  7. user_preferences           — per-user UI stickiness (sticky report
                                  checkboxes, dismissed nudges).
  8. platform_settings          — SahilPay's own KRA PIN + the eTIMS kill switch.

Revision ID: q1a1b2c3d4e5
Revises: p8f1a2b3c4d5
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "q1a1b2c3d4e5"
down_revision = "p8f1a2b3c4d5"
branch_labels = None
depends_on = None


# The four columns added to every table that records money someone must issue a
# KRA invoice for. Identical everywhere, so they are declared once.
def _etims_columns(table: str) -> None:
    op.add_column(table, sa.Column("etims_invoice_number", sa.String(length=64), nullable=True))
    op.add_column(table, sa.Column("etims_issued_at", sa.DateTime(), nullable=True))
    op.add_column(table, sa.Column("etims_qr_url", sa.String(length=512), nullable=True))
    op.add_column(table, sa.Column("etims_entered_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_etims_entered_by_user_id", table, "users",
        ["etims_entered_by_user_id"], ["id"],
    )
    # PARTIAL unique: one eTIMS number identifies one invoice at KRA, but the
    # overwhelming majority of rows have none and must not collide with each other.
    op.create_index(
        f"uq_{table}_etims_invoice_number", table, ["etims_invoice_number"],
        unique=True, postgresql_where=sa.text("etims_invoice_number IS NOT NULL"),
    )


def _drop_etims_columns(table: str) -> None:
    op.drop_index(f"uq_{table}_etims_invoice_number", table_name=table)
    op.drop_constraint(f"fk_{table}_etims_entered_by_user_id", table, type_="foreignkey")
    for col in ("etims_entered_by_user_id", "etims_qr_url",
                "etims_issued_at", "etims_invoice_number"):
        op.drop_column(table, col)


def upgrade():
    # --- 1. property_owners -------------------------------------------------
    op.create_table(
        "property_owners",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("kra_pin", sa.String(length=11), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("landlord_id", "phone", name="uq_property_owners_landlord_phone"),
    )
    op.create_index("ix_property_owners_landlord_id", "property_owners", ["landlord_id"])
    op.create_index("ix_property_owners_phone", "property_owners", ["phone"])

    # --- 2. KRA PIN columns -------------------------------------------------
    # tenants.kra_pin already exists (String(30)) — left alone deliberately, so
    # this migration never has to touch data a tenant already typed.
    op.add_column("users", sa.Column("kra_pin", sa.String(length=11), nullable=True))
    op.add_column("properties", sa.Column("kra_pin", sa.String(length=11), nullable=True))

    # --- 3. Per-property eTIMS opt-in --------------------------------------
    op.add_column("properties", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_properties_owner_id", "properties", "property_owners",
                          ["owner_id"], ["id"])
    op.create_index("ix_properties_owner_id", "properties", ["owner_id"])
    op.add_column(
        "properties",
        sa.Column("etims_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "properties",
        sa.Column("etims_display_settings", postgresql.JSON(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
    )

    # Backfill: every distinct owner_phone under a landlord becomes one owner
    # row, named after the first property it appears on, and every property
    # with that phone points at it. Properties with no owner_phone (the normal
    # case for a self-managing landlord) are left with owner_id NULL.
    op.execute(
        """
        INSERT INTO property_owners (landlord_id, full_name, phone, is_active,
                                     created_at, updated_at)
        SELECT DISTINCT ON (p.landlord_id, p.owner_phone)
               p.landlord_id,
               'Owner of ' || p.name,
               p.owner_phone,
               TRUE,
               NOW(),
               NOW()
          FROM properties p
         WHERE p.owner_phone IS NOT NULL
           AND btrim(p.owner_phone) <> ''
           AND p.is_deleted = FALSE
         ORDER BY p.landlord_id, p.owner_phone, p.id
        """
    )
    op.execute(
        """
        UPDATE properties p
           SET owner_id = o.id
          FROM property_owners o
         WHERE o.landlord_id = p.landlord_id
           AND o.phone = p.owner_phone
           AND p.owner_phone IS NOT NULL
        """
    )

    # --- 4. eTIMS invoice group --------------------------------------------
    for table in ("payments", "owner_payouts", "billing_transactions"):
        _etims_columns(table)

    # --- Account-level master switch + the two reminder toggles -------------
    op.add_column("landlord_settings",
                  sa.Column("etims_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.false()))
    op.add_column("landlord_settings",
                  sa.Column("etims_reminder_record_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.true()))
    op.add_column("landlord_settings",
                  sa.Column("etims_reminder_filing_enabled", sa.Boolean(), nullable=False,
                            server_default=sa.true()))

    # --- 5. Per-property team-member capability -----------------------------
    op.create_table(
        "team_member_property_permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("team_member_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["team_member_id"], ["team_members.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_member_id", "property_id", "permission",
                            name="uq_tmpp_member_property_permission"),
    )
    op.create_index("ix_team_member_property_permissions_team_member_id",
                    "team_member_property_permissions", ["team_member_id"])
    op.create_index("ix_team_member_property_permissions_property_id",
                    "team_member_property_permissions", ["property_id"])
    op.create_index("ix_team_member_property_permissions_permission",
                    "team_member_property_permissions", ["permission"])

    # --- 6. Help Content CMS ------------------------------------------------
    op.create_table(
        "tutorial_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("icon", sa.String(length=60), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible_to_roles", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tutorial_categories_slug", "tutorial_categories",
                    ["slug"], unique=True)

    op.create_table(
        "tutorial_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.String(length=400), nullable=True),
        sa.Column("body_markdown", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible_to_roles", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["tutorial_categories.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tutorial_articles_category_id", "tutorial_articles", ["category_id"])
    op.create_index("ix_tutorial_articles_slug", "tutorial_articles",
                    ["slug"], unique=True)

    op.create_table(
        "tutorial_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("alt_text", sa.String(length=300), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["tutorial_articles.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tutorial_images_article_id", "tutorial_images", ["article_id"])

    # --- 7. user_preferences ------------------------------------------------
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("preferences", postgresql.JSON(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences",
                    ["user_id"], unique=True)

    # --- 8. platform_settings ----------------------------------------------
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kra_pin", sa.String(length=11), nullable=True),
        sa.Column("legal_entity_name", sa.String(length=200), nullable=True),
        sa.Column("etims_features_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO platform_settings (etims_features_enabled, created_at, updated_at) "
        "VALUES (TRUE, NOW(), NOW())"
    )


def downgrade():
    op.drop_table("platform_settings")

    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")

    op.drop_index("ix_tutorial_images_article_id", table_name="tutorial_images")
    op.drop_table("tutorial_images")
    op.drop_index("ix_tutorial_articles_slug", table_name="tutorial_articles")
    op.drop_index("ix_tutorial_articles_category_id", table_name="tutorial_articles")
    op.drop_table("tutorial_articles")
    op.drop_index("ix_tutorial_categories_slug", table_name="tutorial_categories")
    op.drop_table("tutorial_categories")

    op.drop_index("ix_team_member_property_permissions_permission",
                  table_name="team_member_property_permissions")
    op.drop_index("ix_team_member_property_permissions_property_id",
                  table_name="team_member_property_permissions")
    op.drop_index("ix_team_member_property_permissions_team_member_id",
                  table_name="team_member_property_permissions")
    op.drop_table("team_member_property_permissions")

    op.drop_column("landlord_settings", "etims_reminder_filing_enabled")
    op.drop_column("landlord_settings", "etims_reminder_record_enabled")
    op.drop_column("landlord_settings", "etims_enabled")

    for table in ("billing_transactions", "owner_payouts", "payments"):
        _drop_etims_columns(table)

    op.drop_column("properties", "etims_display_settings")
    op.drop_column("properties", "etims_enabled")
    op.drop_index("ix_properties_owner_id", table_name="properties")
    op.drop_constraint("fk_properties_owner_id", "properties", type_="foreignkey")
    op.drop_column("properties", "owner_id")
    op.drop_column("properties", "kra_pin")
    op.drop_column("users", "kra_pin")

    op.drop_index("ix_property_owners_phone", table_name="property_owners")
    op.drop_index("ix_property_owners_landlord_id", table_name="property_owners")
    op.drop_table("property_owners")
