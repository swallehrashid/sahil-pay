"""subscription admin overrides — the owner's word is final

The billing engine recomputed `status` on every page load and re-armed the
grace clock whenever a balance was touched, so an admin who set a status or
extended a due date by hand watched the system quietly undo it minutes later.
Who is paying, when, and on what terms is a commercial conversation the system
cannot see, so these flags let an admin switch the automation off for one
landlord and have their decision stand:

  admin_override_mode   'open' = never lock the portal, 'closed' = always lock,
                        NULL = let the system decide (previous behaviour).
  admin_status_locked   the automation never rewrites `status` again.
  admin_billing_frozen  no auto charge, and next_billing_date never auto-moves.

Defaults preserve today's behaviour exactly for every existing row.

Revision ID: d4f5a6b7c8d9
Revises: d3f4a5b6c7d8
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f5a6b7c8d9"
down_revision = "d3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subscriptions", sa.Column("admin_override_mode", sa.String(length=10), nullable=True))
    op.add_column("subscriptions", sa.Column("admin_status_locked", sa.Boolean(), nullable=False,
                                             server_default=sa.false()))
    op.add_column("subscriptions", sa.Column("admin_billing_frozen", sa.Boolean(), nullable=False,
                                             server_default=sa.false()))
    op.add_column("subscriptions", sa.Column("admin_override_reason", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("admin_override_by", sa.Integer(), nullable=True))
    op.add_column("subscriptions", sa.Column("admin_override_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_subscriptions_admin_override_by", "subscriptions", "users",
                          ["admin_override_by"], ["id"])


def downgrade():
    op.drop_constraint("fk_subscriptions_admin_override_by", "subscriptions", type_="foreignkey")
    for col in ("admin_override_at", "admin_override_by", "admin_override_reason",
                "admin_billing_frozen", "admin_status_locked", "admin_override_mode"):
        op.drop_column("subscriptions", col)
