"""Auto-receipt channels for payments allocated without a human

Revision ID: t1a1b2c3d4e5
Revises: s1a1b2c3d4e5
Create Date: 2026-08-13

A Co-pilot payment that matches and allocates on its own has nobody to press
"send receipt", so the tenant heard nothing. These four columns decide what is
sent, per channel, because their costs differ: SMS is billed per segment while
email and in-app are free.

Defaults are chosen so that switching the feature on later is a single
decision rather than four: the master switch is OFF, and when it is turned on
the free channels are already selected and SMS is not.
"""

from alembic import op
import sqlalchemy as sa


revision = "t1a1b2c3d4e5"
down_revision = "s1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation_settings",
                  sa.Column("auto_receipt_enabled", sa.Boolean(),
                            server_default="false", nullable=False))
    op.add_column("automation_settings",
                  sa.Column("auto_receipt_email", sa.Boolean(),
                            server_default="true", nullable=False))
    # Off by default: an account with a thin SMS balance should not discover
    # this feature by running out of credit.
    op.add_column("automation_settings",
                  sa.Column("auto_receipt_sms", sa.Boolean(),
                            server_default="false", nullable=False))
    op.add_column("automation_settings",
                  sa.Column("auto_receipt_in_app", sa.Boolean(),
                            server_default="true", nullable=False))


def downgrade():
    op.drop_column("automation_settings", "auto_receipt_in_app")
    op.drop_column("automation_settings", "auto_receipt_sms")
    op.drop_column("automation_settings", "auto_receipt_email")
    op.drop_column("automation_settings", "auto_receipt_enabled")
