"""Let existing caretakers actually record a meter reading

Revision ID: z1a1b2c3d4e5
Revises: y1a1b2c3d4e5
Create Date: 2026-08-17

The caretaker preset grants `utilities` edit, and the API accepts the write — but
the Utilities page asks which PROPERTY a meter belongs to, and the preset never
granted `properties` view. The dropdown came back empty, so the form could not
be completed and the reported symptom was "the caretaker cannot add utilities",
even though nothing was refusing the write itself.

The preset is fixed for new members, but a preset is a bootstrap: it is applied
once at creation and never re-run. Caretakers who already exist would stay stuck,
which is precisely the population that hit this. This grants them the missing
VIEW row.

Their property SCOPE is untouched, so a caretaker still sees only the blocks
assigned to them — this adds no visibility they did not already have through
`units` and `tenants`, which the preset always granted.
"""

from alembic import op


revision = "z1a1b2c3d4e5"
down_revision = "y1a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO team_member_permissions
            (team_member_id, module, can_view, can_edit, created_at, updated_at)
        SELECT tm.id, 'properties', true, false, NOW(), NOW()
          FROM team_members tm
         WHERE tm.preset = 'caretaker'
           AND NOT EXISTS (
                 SELECT 1 FROM team_member_permissions e
                  WHERE e.team_member_id = tm.id
                    AND e.module = 'properties')
        """
    )


def downgrade():
    # Only remove the view-only rows this migration could have added; a
    # caretaker later granted edit by hand keeps it.
    op.execute(
        """
        DELETE FROM team_member_permissions p
         USING team_members tm
         WHERE p.team_member_id = tm.id
           AND tm.preset = 'caretaker'
           AND p.module = 'properties'
           AND p.can_view = true
           AND p.can_edit = false
        """
    )
