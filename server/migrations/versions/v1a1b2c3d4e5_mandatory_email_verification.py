"""Mandatory email verification, and a reset token of its own

Revision ID: v1a1b2c3d4e5
Revises: u1a1b2c3d4e5
Create Date: 2026-08-17

Two changes that only make sense together, because the first is unsafe without
the second.

1. SEPARATE PASSWORD-RESET TOKENS FROM VERIFICATION TOKENS.
   Both flows wrote to users.verification_token ("reuse column for reset
   token"), which made them silently destroy each other: requesting a password
   reset invalidated a pending verification link, and clicking a *reset* link
   on the verify-email endpoint marked the address verified and consumed the
   token, so the reset that followed failed as "already used". Harmless while
   verification was optional. Once login depends on being verified, that same
   collision is an account lockout, so the reset flow gets its own column.

2. GRANDFATHER EVERY EXISTING ACCOUNT AS VERIFIED.
   Enforcement is going on for landlords, property managers, team members and
   affiliates. Every account that predates this migration was created under
   rules that never required the click, and a large share never made it — so
   turning the gate on without a backfill would lock out the entire existing
   user base at once, including the operators who would have to fix it.
   Existing ACTIVE accounts are trusted; deactivated ones are deliberately left
   alone, since re-activating one should go through verification.

   Tenants are untouched either way: they sign in with a phone OTP and many
   have no email address at all.
"""

from alembic import op
import sqlalchemy as sa


revision = "v1a1b2c3d4e5"
down_revision = "u1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("password_reset_token", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_users_password_reset_token", "users", ["password_reset_token"], unique=False
    )

    # Move any reset token currently squatting in verification_token across.
    # There is no way to tell the two apart retrospectively, so pending links of
    # both kinds are simply left to expire — the affected user re-requests one.
    # Copying rather than guessing keeps this migration lossless.
    op.execute(
        """
        UPDATE users
           SET password_reset_token = verification_token
         WHERE verification_token IS NOT NULL
           AND is_verified = true
        """
    )

    # Grandfather clause — see the module docstring.
    op.execute(
        """
        UPDATE users
           SET is_verified = true
         WHERE is_active = true
           AND is_verified = false
           AND role <> 'tenant'
        """
    )


def downgrade():
    # Verification state is not rolled back: un-verifying accounts that have
    # since confirmed for real would lock them out on the way down, which is a
    # worse outcome than leaving them verified.
    op.drop_index("ix_users_password_reset_token", table_name="users")
    op.drop_column("users", "password_reset_token")
