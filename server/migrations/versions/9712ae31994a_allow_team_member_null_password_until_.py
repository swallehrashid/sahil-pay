"""allow team_member null password until activation

Revision ID: 9712ae31994a
Revises: 3f49d89141bf
Create Date: 2026-06-27 04:03:57.851508

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9712ae31994a'
down_revision = '3f49d89141bf'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_users_non_tenant_needs_password", "users", type_="check")
    op.create_check_constraint(
        "ck_users_non_tenant_needs_password",
        "users",
        "(role IN ('tenant', 'team_member')) OR (password_hash IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint("ck_users_non_tenant_needs_password", "users", type_="check")
    op.create_check_constraint(
        "ck_users_non_tenant_needs_password",
        "users",
        "(role = 'tenant') OR (password_hash IS NOT NULL)",
    )
