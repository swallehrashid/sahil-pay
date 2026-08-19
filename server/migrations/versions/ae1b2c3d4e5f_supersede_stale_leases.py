"""Retire lease agreements that a newer one has already replaced

Revision ID: ae1b2c3d4e5f
Revises: ad1b2c3d4e5f
Create Date: 2026-08-18

Preparing a lease looks, to a landlord, like it did nothing: the next move
belongs to the tenant, so the screen simply shows "With the tenant" and waits.
The natural response is to press Prepare again — and each press left another
agreement sitting in `sent` for that tenancy, forever.

current_for_tenant() answers "what must I sign?" with the newest agreement still
awaiting the tenant. With a queue of those behind it, the answer went wrong the
moment anything was approved: the tenant signed, the landlord approved, and the
portal immediately presented a DIFFERENT unsigned lease and stopped offering the
download for the one just completed. From the office it read as "the tenant
never signed"; from the tenant's phone as "the lease never arrived".

Sending now supersedes the rest (services/lease_service.supersede_outstanding).
This backfills the same rule over history: for every tenancy, any lease in
draft / sent / rejected that is older than a later agreement for that same
tenancy becomes `superseded`.

Deliberately conservative:
  * the NEWEST outstanding lease per tenancy is left alone — it is very likely
    the one genuinely waiting for a signature, and retiring it would take a real
    agreement off a tenant's screen;
  * `submitted` and `approved` rows are never touched. A signature is evidence
    and is not tidied up by a data migration.

No schema change — `status` is already a plain String(12) and 'superseded' fits.
"""

from alembic import op


revision = "ae1b2c3d4e5f"
down_revision = "ad1b2c3d4e5f"
branch_labels = None
depends_on = None

OUTSTANDING = "('draft', 'sent', 'rejected')"


def upgrade():
    # An outstanding lease is stale when a LATER agreement exists on the same
    # tenancy — whether that later one is signed, approved, or simply the
    # current draft. Ordering is by created_at with id as the tie-break, which
    # matches how current_for_tenant() chooses.
    op.execute(
        f"""
        UPDATE lease_agreements AS stale
           SET status = 'superseded'
          FROM lease_agreements AS newer
         WHERE stale.status IN {OUTSTANDING}
           AND newer.tenant_id = stale.tenant_id
           AND newer.id <> stale.id
           AND (newer.created_at, newer.id) > (stale.created_at, stale.id)
        """
    )


def downgrade():
    # Back to 'sent': these rows were only ever draft/sent/rejected, and 'sent'
    # is the state the overwhelming majority were in. The distinction is not
    # recoverable, which is worth stating rather than pretending otherwise.
    op.execute("UPDATE lease_agreements SET status = 'sent' WHERE status = 'superseded'")
