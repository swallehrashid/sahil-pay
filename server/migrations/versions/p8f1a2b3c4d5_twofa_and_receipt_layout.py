"""Phase 3.4 / 9 — two-factor auth columns + per-landlord receipt layout

  * users.totp_secret          — the TOTP shared secret, ENCRYPTED at rest
                                 (Fernet). Anyone holding it can mint valid
                                 codes forever, so it is never stored in clear.
  * users.totp_enabled         — whether the second factor is active.
  * users.totp_backup_codes    — JSON list of SALTED HASHES of one-time backup
                                 codes; the plaintext is shown once at enrolment
                                 and never stored.
  * users.totp_confirmed_at    — when enrolment was completed.
  * landlord_settings.receipt_layout_json — the landlord's receipt layout
                                 (paper size, header slot arrangement, density).
                                 NULL means "the built-in default", so existing
                                 landlords keep exactly the receipt they have.

Revision ID: p8f1a2b3c4d5
Revises: p5e1f2a3b4c5
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa


revision = "p8f1a2b3c4d5"
down_revision = "p5e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("totp_secret", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("totp_backup_codes", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(), nullable=True))

    op.add_column(
        "landlord_settings",
        sa.Column("receipt_layout_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("landlord_settings", "receipt_layout_json")
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
