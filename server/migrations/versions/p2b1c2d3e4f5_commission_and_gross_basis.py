"""Phase 2 — per-property commission rate + report gross basis

A Kenyan property manager may charge commission ONLY on rent collected — this
month's rent and rent arrears — never on a rent deposit (held, refundable money
belonging to the tenant) and, by convention, not on utilities either.

  * properties.commission_rate        — the manager's percentage on rent collected.
  * landlord_settings.report_gross_basis — 'all' (every collection, the legacy
    behaviour) or 'rent_only'. Persisted so the choice sticks between sessions.

Revision ID: p2b1c2d3e4f5
Revises: p1a1b2c3d4e5
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "p2b1c2d3e4f5"
down_revision = "p1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("properties", sa.Column("commission_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "landlord_settings",
        sa.Column("report_gross_basis", sa.String(length=10), nullable=False, server_default="all"),
    )


def downgrade():
    op.drop_column("landlord_settings", "report_gross_basis")
    op.drop_column("properties", "commission_rate")
