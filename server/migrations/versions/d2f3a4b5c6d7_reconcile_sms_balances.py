"""reconcile every landlord's sms_balance to the confirmed-payment source of truth

landlords.sms_balance was a free-running counter with no memory: +credits on a
confirmed purchase, -credits on a send. One M-Pesa payment confirmed twice — the
STK callback and the C2B confirmation of the same money — credited twice and the
extra stuck forever, which is how a landlord who bought 1,000 credits read 2,000.

This heals the drift on deploy. For every real (non-demo) landlord it rebuilds
the balance from events that actually happened and can be trusted:

    balance = confirmed-purchase credits   (one grant per M-Pesa receipt)
            + genuine admin manual credits (excluding reconciliation rows)
            - credits used on charged sends (communication_logs.sms_credits)

Each distinct receipt is counted once, so the duplicate confirmations collapse.
Failed, pending-unconfirmed and reversed payments contribute nothing. Every
balance that moves is recorded in sms_landlord_credits with a 'SYS-RECON:' reason
so the correction is visible in the landlord's credit history and the move is
traceable. Clean accounts (no duplicate, nothing reversed) compute back to the
exact balance they already had and are left untouched.

Requires d1f2a3b4c5d6 (communication_logs.sms_credits) to have populated usage.

The down migration is a no-op on purpose: the pre-fix balances were inflated
drift, not a state worth restoring.

Revision ID: d2f3a4b5c6d7
Revises: d1f2a3b4c5d6
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "d2f3a4b5c6d7"
down_revision = "d1f2a3b4c5d6"
branch_labels = None
depends_on = None


# Common table expressions for the per-landlord truth. Reused by the audit
# INSERT and the balance UPDATE so both read identical numbers from the
# still-unchanged balances.
_TRUTH_CTE = """
WITH purchased AS (
    -- One grant per distinct M-Pesa receipt; receiptless (legacy self-reported)
    -- rows keyed on their own id so each counts once. Verified, not reversed.
    SELECT landlord_id, SUM(sms_count) AS credits FROM (
        SELECT DISTINCT ON (landlord_id, COALESCE(payment_reference, 'txn:' || id::text))
               landlord_id, id, sms_count
        FROM billing_transactions
        WHERE type = 'sms_purchase'
          AND is_verified = true
          AND is_reversed = false
          AND sms_count IS NOT NULL
        ORDER BY landlord_id, COALESCE(payment_reference, 'txn:' || id::text), id
    ) deduped
    GROUP BY landlord_id
),
manual AS (
    SELECT landlord_id, SUM(credits_added) AS credits
    FROM sms_landlord_credits
    WHERE reason NOT LIKE 'SYS-RECON:%'
    GROUP BY landlord_id
),
used AS (
    SELECT landlord_id, SUM(COALESCE(sms_credits, 0)) AS credits
    FROM communication_logs
    WHERE message_type = 'sms'
    GROUP BY landlord_id
),
truth AS (
    SELECT l.id AS landlord_id,
           l.sms_balance AS before_bal,
           COALESCE(p.credits, 0) AS purchased,
           COALESCE(m.credits, 0) AS manual,
           COALESCE(u.credits, 0) AS used,
           GREATEST(0, COALESCE(p.credits, 0) + COALESCE(m.credits, 0)
                       - COALESCE(u.credits, 0)) AS target
    FROM landlords l
    LEFT JOIN purchased p ON p.landlord_id = l.id
    LEFT JOIN manual    m ON m.landlord_id = l.id
    LEFT JOIN used      u ON u.landlord_id = l.id
    WHERE l.is_demo = false
)
"""


def upgrade():
    conn = op.get_bind()

    # 1) Record every correction in the per-landlord credit ledger first, while
    #    the balances still hold their old values (so before_bal is the old one).
    conn.execute(sa.text(_TRUTH_CTE + """
        INSERT INTO sms_landlord_credits
            (landlord_id, admin_user_id, credits_added, balance_after, reason, created_at)
        SELECT landlord_id,
               NULL,
               target - before_bal,
               target,
               'SYS-RECON: rebuilt from confirmed payments (' || purchased
                   || ' purchased + ' || manual || ' manual - ' || used
                   || ' used); was ' || before_bal || '.',
               (now() AT TIME ZONE 'utc')
        FROM truth
        WHERE target <> before_bal
    """))

    # 2) Apply the rebuilt balances.
    conn.execute(sa.text(_TRUTH_CTE + """
        UPDATE landlords
        SET sms_balance = truth.target
        FROM truth
        WHERE landlords.id = truth.landlord_id
          AND truth.target <> truth.before_bal
    """))


def downgrade():
    # Nothing to restore — the previous balances were drift, not a prior state.
    pass
