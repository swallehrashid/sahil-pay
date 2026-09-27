"""cascade clean-up, one phone format, queued-charge review, queued auto-invoicing

1. HEADLESS TENANTS AND UNITS — properties used to be deleted on their own, so
   their units and every tenant in them stayed live. Every unit whose property
   is deleted, and every tenant whose unit (or its property) is deleted, is
   soft-deleted now; any charge still queued for such a unit is cancelled.
   Invoices and payments are untouched.

2. PHONES — every tenant, team member and user phone number that is a Kenyan
   mobile in any spelling (07…, 7…, +254…, 254…) is rewritten as 254XXXXXXXXX,
   the one form the app now stores and sends. Anything else is left as it was.

3. QUEUE REVIEW — queued_charges gains reviewed_by / reviewed_at / review_note.
   Existing rows keep their status (queued = already approved).

4. AUTOMATION — automation_settings.auto_invoice_queued_charges, OFF for every
   account. The 1st-of-month run now only invoices accounts that turned it on.

Revision ID: ai1b2c3d4e5f
Revises: ah1b2c3d4e5f
"""

import sqlalchemy as sa
from alembic import op

revision = "ai1b2c3d4e5f"
down_revision = "ah1b2c3d4e5f"
branch_labels = None
depends_on = None


_CANONICAL_PHONE = r"""
    CASE
      WHEN regexp_replace({col}, '\D', '', 'g') ~ '^0[17][0-9]{{8}}$'
        THEN '254' || substr(regexp_replace({col}, '\D', '', 'g'), 2)
      WHEN regexp_replace({col}, '\D', '', 'g') ~ '^[17][0-9]{{8}}$'
        THEN '254' || regexp_replace({col}, '\D', '', 'g')
      WHEN regexp_replace({col}, '\D', '', 'g') ~ '^254[17][0-9]{{8}}$'
        THEN regexp_replace({col}, '\D', '', 'g')
      ELSE {col}
    END
"""


def _normalise(table, column):
    expr = _CANONICAL_PHONE.format(col=column)
    op.execute(f"UPDATE {table} SET {column} = {expr} "
               f"WHERE {column} IS NOT NULL AND {column} <> {expr}")


def upgrade():
    with op.batch_alter_table("queued_charges") as batch:
        batch.add_column(sa.Column("reviewed_by_user_id", sa.Integer(),
                                   sa.ForeignKey("users.id"), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("review_note", sa.String(255), nullable=True))

    with op.batch_alter_table("automation_settings") as batch:
        batch.add_column(sa.Column("auto_invoice_queued_charges", sa.Boolean(),
                                   nullable=False, server_default=sa.false()))

    # 1. Headless units and tenants.
    op.execute("""
        UPDATE units SET is_deleted = TRUE, deleted_at = COALESCE(deleted_at, NOW()), is_occupied = FALSE
        WHERE is_deleted = FALSE
          AND property_id IN (SELECT id FROM properties WHERE is_deleted = TRUE)
    """)
    op.execute("""
        UPDATE tenant_unit_history SET moved_out_at = CURRENT_DATE
        WHERE moved_out_at IS NULL
          AND tenant_id IN (SELECT t.id FROM tenants t JOIN units u ON u.id = t.unit_id
                            WHERE t.is_deleted = FALSE AND u.is_deleted = TRUE)
    """)
    op.execute("""
        UPDATE tenants SET is_deleted = TRUE, deleted_at = COALESCE(deleted_at, NOW()),
                           move_out_date = COALESCE(move_out_date, CURRENT_DATE)
        WHERE is_deleted = FALSE
          AND unit_id IN (SELECT id FROM units WHERE is_deleted = TRUE)
    """)
    op.execute("""
        UPDATE queued_charges SET status = 'cancelled'
        WHERE status = 'queued'
          AND unit_id IN (SELECT id FROM units WHERE is_deleted = TRUE)
    """)

    # 2. One phone format.
    for table, column in (("tenants", "phone"), ("tenants", "secondary_phone"),
                          ("team_members", "phone"), ("users", "phone")):
        _normalise(table, column)


def downgrade():
    with op.batch_alter_table("automation_settings") as batch:
        batch.drop_column("auto_invoice_queued_charges")
    with op.batch_alter_table("queued_charges") as batch:
        batch.drop_column("review_note")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
