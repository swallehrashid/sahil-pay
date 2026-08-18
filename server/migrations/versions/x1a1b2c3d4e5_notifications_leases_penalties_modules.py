"""Give notifications, leases and penalties their own permission modules

Revision ID: x1a1b2c3d4e5
Revises: w1a1b2c3d4e5
Create Date: 2026-08-17

Three areas of the product had no permission module of their own and borrowed
one that meant something else:

  leases        gated on `tenants`  — so letting somebody read a tenancy
                agreement also handed them edit rights over tenant records.
  penalties     gated on `invoices` and `reports` — a late-payment charge is
                not an invoice, and reconciling one is not running a report.
  notifications gated on nothing at all, while the send endpoint refused every
                team member outright by ROLE. A secretary with a complete
                permission matrix still could not send a notification, which is
                the reported "team members' notifications are not active
                despite them having permissions".

This is data-only: the module column is a free-text String(30), so no schema
change is needed — only the backfill, which is the part that matters. Every
existing member is granted the new module at exactly the access their old proxy
gave them, so this migration changes NOBODY's effective permissions:

    leases        <- their `tenants` row
    penalties     <- their `invoices` row, else their `reports` row
    notifications <- view for every active member (they already received
                     notifications; only sending was blocked), plus edit for
                     members whose role is 'editor', who could already edit
                     everything else they held.

Members who held no proxy row get no new row — they had no access before and
must not silently acquire any here.
"""

from alembic import op


revision = "x1a1b2c3d4e5"
down_revision = "w1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    # leases <- tenants
    op.execute(
        """
        INSERT INTO team_member_permissions
            (team_member_id, module, can_view, can_edit, created_at, updated_at)
        SELECT p.team_member_id, 'leases', p.can_view, p.can_edit, NOW(), NOW()
          FROM team_member_permissions p
         WHERE p.module = 'tenants'
           AND NOT EXISTS (
                 SELECT 1 FROM team_member_permissions e
                  WHERE e.team_member_id = p.team_member_id
                    AND e.module = 'leases')
        """
    )

    # penalties <- invoices, falling back to reports for members who hold only
    # the latter. DISTINCT ON keeps one row per member with invoices winning.
    op.execute(
        """
        INSERT INTO team_member_permissions
            (team_member_id, module, can_view, can_edit, created_at, updated_at)
        SELECT DISTINCT ON (p.team_member_id)
               p.team_member_id, 'penalties', p.can_view, p.can_edit, NOW(), NOW()
          FROM team_member_permissions p
         WHERE p.module IN ('invoices', 'reports')
           AND NOT EXISTS (
                 SELECT 1 FROM team_member_permissions e
                  WHERE e.team_member_id = p.team_member_id
                    AND e.module = 'penalties')
         ORDER BY p.team_member_id,
                  CASE p.module WHEN 'invoices' THEN 0 ELSE 1 END
        """
    )

    # notifications: everyone active could already RECEIVE them; only sending
    # was blocked, and only for team members. Editors get edit.
    op.execute(
        """
        INSERT INTO team_member_permissions
            (team_member_id, module, can_view, can_edit, created_at, updated_at)
        SELECT tm.id, 'notifications', true,
               COALESCE(tm.role = 'editor', false), NOW(), NOW()
          FROM team_members tm
         WHERE tm.is_active = true
           AND NOT EXISTS (
                 SELECT 1 FROM team_member_permissions e
                  WHERE e.team_member_id = tm.id
                    AND e.module = 'notifications')
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM team_member_permissions
         WHERE module IN ('notifications', 'leases', 'penalties')
        """
    )
