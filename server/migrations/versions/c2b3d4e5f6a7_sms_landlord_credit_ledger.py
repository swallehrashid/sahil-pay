"""Per-landlord manual SMS-credit ledger.

Adds sms_landlord_credits: an append-only ledger of admin manual adjustments to
a single landlord's sms_balance, used while automated M-Pesa billing is being
finalised (landlord pays the operator directly, admin credits the equivalent
SMS here). Every row carries a mandatory reason and the acting admin, so a
manual credit is always traceable and reversible.

Revision ID: c2b3d4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "c2b3d4e5f6a7"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sms_landlord_credits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("credits_added", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sms_landlord_credits_landlord_id",
        "sms_landlord_credits", ["landlord_id"],
    )
    op.create_index(
        "ix_sms_landlord_credits_admin_user_id",
        "sms_landlord_credits", ["admin_user_id"],
    )


def downgrade():
    op.drop_index("ix_sms_landlord_credits_admin_user_id", table_name="sms_landlord_credits")
    op.drop_index("ix_sms_landlord_credits_landlord_id", table_name="sms_landlord_credits")
    op.drop_table("sms_landlord_credits")
