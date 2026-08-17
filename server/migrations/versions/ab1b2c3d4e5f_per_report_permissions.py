"""Which reports a team member may open, not just whether they may open reports

Revision ID: ab1b2c3d4e5f
Revises: aa1b2c3d4e5f
Create Date: 2026-08-17

`reports: view` was one grant covering a bucket that holds both a property
statement an owner is entitled to and the payments report, arrears list and
portfolio comparatives for the whole managed book. Giving an owner their own
statement meant giving them all of it, so in practice owners were given nothing
and sent PDFs by hand.

allowed_reports narrows the same row:

    NULL  -> every report        (what every existing row means)
    [...] -> only these keys
    []    -> none

NULL and [] are deliberately different, and the column is nullable rather than
defaulting to []: an empty-list default would silently revoke reports from every
existing team member the moment this deployed. NULL preserves what they have,
and [] stays available as a real choice.

The one exception is the `owner` preset, which is backfilled to the property
statement alone — an owner login exists to see one block's figures, and the
whole point of this change is that it should not also expose the managing
agent's payments report. Members created from any other preset, or hand-tuned,
are left at NULL: silently narrowing a working permission is not this
migration's business.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ab1b2c3d4e5f"
down_revision = "aa1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "team_member_permissions",
        sa.Column("allowed_reports",
                  postgresql.JSON(astext_type=sa.Text()),
                  nullable=True),
    )

    # Owner logins: their own block's statement, nothing else.
    op.execute(
        """
        UPDATE team_member_permissions p
           SET allowed_reports = '["property"]'::json
          FROM team_members tm
         WHERE p.team_member_id = tm.id
           AND p.module = 'reports'
           AND tm.preset = 'owner'
        """
    )


def downgrade():
    op.drop_column("team_member_permissions", "allowed_reports")
