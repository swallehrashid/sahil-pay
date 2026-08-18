"""Notes on a maintenance request

Revision ID: aa1b2c3d4e5f
Revises: z1a1b2c3d4e5
Create Date: 2026-08-17

A maintenance request had a status and nothing else. A status cannot carry
"plumber booked for Tuesday", "tenant not home, rebooked", or "third leak on
that stack this year" — so those went into WhatsApp and were lost the moment the
person holding them was on leave.

`is_internal` keeps two audiences on one thread: an office note about what a
contractor quoted is not for the tenant, while "we'll be there Tuesday" is.
Tenant-authored comments are never internal, since they wrote them.

author_user_id is nullable because an OTP-only tenant has no User row; the
display name is snapshotted next to it so a comment still reads correctly after
the author's record changes.
"""

from alembic import op
import sqlalchemy as sa


revision = "aa1b2c3d4e5f"
down_revision = "z1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("author_role", sa.String(length=20), nullable=False),
        sa.Column("author_name", sa.String(length=120), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["maintenance_requests.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_maintenance_comments_request_id",
                    "maintenance_comments", ["request_id"])
    op.create_index("ix_maintenance_comments_author_user_id",
                    "maintenance_comments", ["author_user_id"])


def downgrade():
    op.drop_index("ix_maintenance_comments_author_user_id",
                  table_name="maintenance_comments")
    op.drop_index("ix_maintenance_comments_request_id",
                  table_name="maintenance_comments")
    op.drop_table("maintenance_comments")
