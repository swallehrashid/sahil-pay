"""Phase 5 — back-link existing tenant rows to their login user

No schema change: tenants.user_id already allows many rows per user; what
changed is the ORM relationship (User.tenant_profile 1:1 → tenant_profiles 1:N).

This is the DATA half: a tenant who rents several units today has one Tenant row
per unit, and typically only ONE of them is linked to their login. The others
have user_id = NULL, so signing in shows one unit and hides the rest.

Matching rule — the same one services/tenant_identity_service.py uses at
runtime: the last 9 digits of the phone (so 0712…, 254712… and +254 712… are one
person), or a lowercased email. Deliberately conservative: a row is linked only
when EXACTLY ONE candidate user matches, because a wrong link would show one
person another person's balances. Ambiguous rows are left alone and get linked
naturally the next time that tenant signs in.

Revision ID: p5e1f2a3b4c5
Revises: p6d1e2f3a4b5
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa


revision = "p5e1f2a3b4c5"
down_revision = "p6d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Link by phone tail, only where exactly one tenant-role user matches.
    conn.execute(sa.text("""
        WITH candidates AS (
            SELECT t.id AS tenant_id,
                   MIN(u.id) AS user_id,
                   COUNT(DISTINCT u.id) AS matches
            FROM tenants t
            JOIN users u
              ON u.role = 'tenant'
             AND u.phone IS NOT NULL
             AND t.phone IS NOT NULL
             AND RIGHT(REGEXP_REPLACE(u.phone, '\\D', '', 'g'), 9)
               = RIGHT(REGEXP_REPLACE(t.phone, '\\D', '', 'g'), 9)
             AND LENGTH(REGEXP_REPLACE(t.phone, '\\D', '', 'g')) >= 9
            WHERE t.user_id IS NULL
              AND t.is_deleted = false
            GROUP BY t.id
        )
        UPDATE tenants
        SET user_id = candidates.user_id
        FROM candidates
        WHERE tenants.id = candidates.tenant_id
          AND candidates.matches = 1
    """))

    # Then by email, for rows the phone pass could not resolve.
    conn.execute(sa.text("""
        WITH candidates AS (
            SELECT t.id AS tenant_id,
                   MIN(u.id) AS user_id,
                   COUNT(DISTINCT u.id) AS matches
            FROM tenants t
            JOIN users u
              ON u.role = 'tenant'
             AND u.email IS NOT NULL
             AND t.email IS NOT NULL
             AND LOWER(u.email) = LOWER(t.email)
            WHERE t.user_id IS NULL
              AND t.is_deleted = false
            GROUP BY t.id
        )
        UPDATE tenants
        SET user_id = candidates.user_id
        FROM candidates
        WHERE tenants.id = candidates.tenant_id
          AND candidates.matches = 1
    """))


def downgrade():
    # Intentionally not reversed: we cannot tell which links this migration
    # created from links that already existed, and unlinking a real tenant from
    # their login would lock them out of their own portal.
    pass
