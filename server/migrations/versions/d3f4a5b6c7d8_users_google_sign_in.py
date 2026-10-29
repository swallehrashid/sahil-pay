"""users.google_sub + allow Google accounts to have no password

Adds the Google subject id (the `sub` claim from a verified Google ID token,
Google's stable per-user identifier) so a landlord or affiliate who continues
with Google is linked to their Google identity, and relaxes the
non-tenant-needs-password check so such an account is valid with no password
until the holder sets one.

Revision ID: d3f4a5b6c7d8
Revises: d2f3a4b5c6d7
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "d3f4a5b6c7d8"
down_revision = "d2f3a4b5c6d7"
branch_labels = None
depends_on = None

_CK = "ck_users_non_tenant_needs_password"


def upgrade():
    op.add_column("users", sa.Column("google_sub", sa.String(length=64), nullable=True))
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    op.drop_constraint(_CK, "users", type_="check")
    op.create_check_constraint(
        _CK, "users",
        "(role IN ('tenant', 'team_member')) "
        "OR (password_hash IS NOT NULL) "
        "OR (google_sub IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint(_CK, "users", type_="check")
    op.create_check_constraint(
        _CK, "users",
        "(role IN ('tenant', 'team_member')) OR (password_hash IS NOT NULL)",
    )
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
