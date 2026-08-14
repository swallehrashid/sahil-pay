"""Lease agreements — portal-signed and scanned, in one table

Revision ID: u1a1b2c3d4e5
Revises: t1a1b2c3d4e5
Create Date: 2026-08-13

Both routes to a signed lease land here: the tenant filling in and signing the
agreement in their portal, and a lease signed on paper then photographed. A
landlord asking "do I have a signed lease for this unit?" should not have to
ask the question twice.

The signature columns are audit evidence — typed name, timestamp, IP and user
agent, captured once at submission. They are what makes the record hold up
later; nothing in the application updates them after the fact.
"""

from alembic import op
import sqlalchemy as sa


revision = "u1a1b2c3d4e5"
down_revision = "t1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lease_agreements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("template_id", sa.Integer(), nullable=True),

        sa.Column("status", sa.String(length=12), server_default="draft", nullable=False),
        sa.Column("source", sa.String(length=10), server_default="portal", nullable=False),

        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("field_values", sa.JSON(), server_default="{}", nullable=False),

        sa.Column("signed_name", sa.String(length=200), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("signed_ip", sa.String(length=45), nullable=True),
        sa.Column("signed_user_agent", sa.String(length=400), nullable=True),

        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),

        sa.Column("document_url", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),

        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        # Deliberately NOT ondelete=CASCADE: deleting a template must never
        # delete the agreements it produced.
        sa.ForeignKeyConstraint(["template_id"], ["document_templates.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    for col in ("landlord_id", "tenant_id", "unit_id", "property_id", "template_id"):
        op.create_index(f"ix_lease_agreements_{col}", "lease_agreements", [col])
    op.create_index("ix_lease_agreements_status", "lease_agreements", ["status"])
    op.create_index("ix_lease_agreements_tenant_status", "lease_agreements",
                    ["tenant_id", "status"])
    op.create_index("ix_lease_agreements_landlord_status", "lease_agreements",
                    ["landlord_id", "status"])


def downgrade():
    for name in ("ix_lease_agreements_landlord_status",
                 "ix_lease_agreements_tenant_status",
                 "ix_lease_agreements_status"):
        op.drop_index(name, table_name="lease_agreements")
    for col in ("landlord_id", "tenant_id", "unit_id", "property_id", "template_id"):
        op.drop_index(f"ix_lease_agreements_{col}", table_name="lease_agreements")
    op.drop_table("lease_agreements")
