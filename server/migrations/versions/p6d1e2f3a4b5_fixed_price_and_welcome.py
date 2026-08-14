"""Phase 6/7 — landlord fixed monthly price + per-landlord SMS price override

  * landlords.fixed_monthly_price — a negotiated flat monthly fee that
    overrides per-unit pricing entirely. The figure is agreed verbally and is
    already a discount, so billing-cycle discounts do NOT stack on top of it.
  * landlords.sms_price_override (Phase 13) — a per-landlord price per SMS,
    winning over the global SmsPricingConfig for that landlord.

Revision ID: p6d1e2f3a4b5
Revises: p4c1d2e3f4a5
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "p6d1e2f3a4b5"
down_revision = "p4c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("landlords", sa.Column("fixed_monthly_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("landlords", sa.Column("sms_price_override", sa.Numeric(8, 4), nullable=True))


def downgrade():
    op.drop_column("landlords", "sms_price_override")
    op.drop_column("landlords", "fixed_monthly_price")
