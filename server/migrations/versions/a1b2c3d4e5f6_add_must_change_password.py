"""add users.must_change_password

Adds a boolean flag set when an account is on a system-issued temporary
password (team members created by a landlord). The frontend forces a
password change on next login and the flag is cleared when they set their own.

Revision ID: a1b2c3d4e5f6
Revises: 3eb9cc353712
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "3eb9cc353712"
branch_labels = None
depends_on = None


def upgrade():
    # server_default backfills existing rows; NOT NULL afterwards is then safe.
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Drop the server default so the ORM-level default is the single source of truth.
    op.alter_column("users", "must_change_password", server_default=None)


def downgrade():
    op.drop_column("users", "must_change_password")
