"""communication_logs.sms_credits — persist the credits each send burned

The SMS balance is being made a derivable figure (purchases − usage), and the
usage side needs the credits ACTUALLY charged per message. The existing
``sms_segments`` column is the raw GSM-7 segment count, a different unit: a
short message can be one segment yet several credits under the admin word→credit
tiers, which is the unit the balance is decremented by. So a new column records
the charged credits going forward.

This migration also backfills history so usage is a concrete, frozen number for
rows written before the column existed, computed the same way the send computed
it at the time: ``credits_for_words`` over the live word→credit tiers, but only
for SMS rows that were actually charged. "Charged" is read as delivered/pending
with a non-zero resale charge OR a non-zero platform cost — the platform cost
matters because a landlord on a negotiated rate of 0.00 is charged credits while
their sms_charge is legitimately 0, and keying on sms_charge alone would have
understated their usage and inflated their rebuilt balance.

Failed, demo and own-provider-key sends recorded no charge at all, so they
backfill to 0 and correctly count as no usage.

Data + schema. The down migration drops the column.

Revision ID: d1f2a3b4c5d6
Revises: aj1b2c3d4e5f
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "d1f2a3b4c5d6"
down_revision = "aj1b2c3d4e5f"
branch_labels = None
depends_on = None


# Pure, import-safe helpers — no Flask app context needed, so they are a
# duplicate of services/sms_billing's logic kept local to the migration (a
# migration must not depend on service code that may change under it later).
_DEFAULT_RANGES = [(1, 25, 1), (26, 50, 2), (51, 75, 3), (76, 100, 4), (101, None, 5)]


def _credits_for_words(wc: int, ranges) -> int:
    wc = max(1, int(wc or 0))
    for mn, mx, cr in ranges:
        if wc >= mn and (mx is None or wc <= mx):
            return int(cr)
    return 1


def upgrade():
    op.add_column("communication_logs", sa.Column("sms_credits", sa.Integer(), nullable=True))

    conn = op.get_bind()

    # Every non-charged SMS row is zero usage — set that outright.
    conn.execute(sa.text(
        """
        UPDATE communication_logs
        SET sms_credits = 0
        WHERE message_type = 'sms'
          AND (status = 'failed'
               OR (COALESCE(sms_charge, 0) <= 0 AND COALESCE(platform_cost, 0) <= 0))
        """
    ))

    # Live word→credit tiers, exactly what the sender billed by (fallback to the
    # market defaults if the table was never seeded).
    rows = conn.execute(sa.text(
        "SELECT min_words, max_words, credits FROM sms_credit_ranges ORDER BY min_words"
    )).fetchall()
    ranges = [(r[0], r[1], r[2]) for r in rows] or _DEFAULT_RANGES

    # Charged SMS rows: credits from the message's word count. Group ids by the
    # resulting credit value (there are only a handful of tiers) so the whole
    # backfill is a few bulk UPDATEs rather than one per row.
    charged = conn.execute(sa.text(
        """
        SELECT id, content FROM communication_logs
        WHERE message_type = 'sms'
          AND status <> 'failed'
          AND (COALESCE(sms_charge, 0) > 0 OR COALESCE(platform_cost, 0) > 0)
        """
    )).fetchall()

    ids_by_credit: dict[int, list[int]] = {}
    for row_id, content in charged:
        wc = len((content or "").split())
        credits = _credits_for_words(wc, ranges)
        ids_by_credit.setdefault(credits, []).append(row_id)

    for credits, ids in ids_by_credit.items():
        # Chunk the IN list so a very long history still issues sane statements.
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            conn.execute(
                sa.text("UPDATE communication_logs SET sms_credits = :c WHERE id = ANY(:ids)"),
                {"c": credits, "ids": chunk},
            )


def downgrade():
    op.drop_column("communication_logs", "sms_credits")
