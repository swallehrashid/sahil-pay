"""Phase 4 — tenant payment score

A percentage out of 100 measuring how reliably a tenant has paid RENT since
they moved in. Persisted (rather than computed per request) because it is shown
in every tenant list across four portals; recomputed on payment and nightly.

Revision ID: p4c1d2e3f4a5
Revises: p2b1c2d3e4f5
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "p4c1d2e3f4a5"
down_revision = "p2b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("tenant_score", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("tenant_score_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("tenants", "tenant_score_updated_at")
    op.drop_column("tenants", "tenant_score")
