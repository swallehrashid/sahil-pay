"""Saved column mappings for the bulk importer

Revision ID: ac1b2c3d4e5f
Revises: ab1b2c3d4e5f
Create Date: 2026-08-17

The bulk importer reads whatever headers a spreadsheet happens to have and lets
the caller say which column means what. That mapping is worth keeping: the same
shape arrives every month, and re-pointing fifteen columns by hand each time is
the step that makes people abandon an importer and go back to typing.

`options` sits alongside `mapping` so a saved setup reproduces the whole import,
not just the columns — notably whether account numbers are auto-composed and
with which separator, which changes what every row will be given.

Unique on (landlord, entity, name) so "Monthly units" can exist for units and
for tenants without colliding, while one account cannot end up with two
different mappings under the same name.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ac1b2c3d4e5f"
down_revision = "ab1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mapping", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("options", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["landlord_id"], ["landlords.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("landlord_id", "entity", "name",
                            name="uq_import_mapping_landlord_entity_name"),
    )
    op.create_index("ix_import_mappings_landlord_id", "import_mappings", ["landlord_id"])


def downgrade():
    op.drop_index("ix_import_mappings_landlord_id", table_name="import_mappings")
    op.drop_table("import_mappings")
