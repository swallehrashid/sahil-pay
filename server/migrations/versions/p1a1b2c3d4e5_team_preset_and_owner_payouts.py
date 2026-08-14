"""Phase 1 — team member role presets, owner monthly statements, owner payouts

Three property-manager-scale additions (OPUS_EXECUTION_SPEC.md Phase 1):

  1. team_members.preset — which role preset a member was created from
     (owner | caretaker | accountant | secretary | custom). Labelling and
     bootstrap only; team_member_permissions stays the authority on access.
  2. automation_settings.owner_reports_enabled / owner_reports_day — the
     monthly "email each owner their property statement" automation.
  3. owner_payouts — the ledger of money a property manager has remitted to
     each property's owner. Informational on the property statement; NEVER an
     expense, so it must not touch tax or expense maths.

Revision ID: p1a1b2c3d4e5
Revises: d7e8f9a0b1c2
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "p1a1b2c3d4e5"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    # --- 1. Team member presets --------------------------------------------
    op.add_column("team_members", sa.Column("preset", sa.String(length=20), nullable=True))

    # --- 2. Owner monthly statement automation ------------------------------
    op.add_column(
        "automation_settings",
        sa.Column("owner_reports_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "automation_settings",
        sa.Column("owner_reports_day", sa.Integer(), nullable=True),
    )

    # --- 3. Owner payouts ----------------------------------------------------
    op.create_table(
        "owner_payouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("landlord_id", sa.Integer(), sa.ForeignKey("landlords.id"), nullable=False, index=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payout_date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=True, index=True),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # The statement pulls payouts for one property over a date window.
    op.create_index(
        "ix_owner_payouts_property_date", "owner_payouts", ["property_id", "payout_date"]
    )


def downgrade():
    op.drop_index("ix_owner_payouts_property_date", table_name="owner_payouts")
    op.drop_table("owner_payouts")
    op.drop_column("automation_settings", "owner_reports_day")
    op.drop_column("automation_settings", "owner_reports_enabled")
    op.drop_column("team_members", "preset")
