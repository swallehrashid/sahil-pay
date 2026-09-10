"""landlord document theme colours

Two nullable colour columns on landlord_settings. NULL means "the Sahil Pay
default palette", which is what every existing account has and what
services/receipt_theme.py falls back to — so this migration changes the
appearance of exactly nothing until a landlord opens the screen and picks.

Revision ID: b4e2546695a4
Revises: ag1b2c3d4e5f
"""

from alembic import op
import sqlalchemy as sa

revision = "b4e2546695a4"
down_revision = "ag1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("landlord_settings", sa.Column("theme_primary", sa.String(length=7), nullable=True))
    op.add_column("landlord_settings", sa.Column("theme_secondary", sa.String(length=7), nullable=True))


def downgrade():
    op.drop_column("landlord_settings", "theme_secondary")
    op.drop_column("landlord_settings", "theme_primary")
