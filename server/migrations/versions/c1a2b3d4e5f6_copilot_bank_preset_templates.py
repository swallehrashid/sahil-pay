"""Add tolerant Co-pilot parser presets for the major Kenyan banks.

The original migration (5789a1551068) shipped only M-Pesa/KCB/Equity templates.
Real deployments forward SMS from many banks whose credit-alert wording the
parser had no template for, so those messages sat in the unparsed queue forever
even though a sender existed. Combined with the tolerant-literal parser change
in services/copilot_service.py (connector synonyms + optional punctuation),
these presets cover the common credit-alert formats for Co-op, NCBA, Absa,
Family Bank, DTB, Stanbic and I&M, plus an extra M-Pesa till/received variant.

Idempotent: each row is inserted only if no template with the same
(name, sender_id) already exists, so re-running is safe and it never clobbers a
template an admin edited.

Revision ID: c1a2b3d4e5f6
Revises: b3c4d5e6f7a8
Create Date: 2026-07-22
"""
from alembic import op

revision = "c1a2b3d4e5f6"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


# (name, sender_id, template_text, sample_text, priority)
_PRESETS = [
    ("Co-op Bank credit", "CO-OP BANK",
     "{*}received Ksh{amount} from {name} to your account {account}. Ref {ref}{*}",
     "Dear customer, you have received Ksh2,500.00 from MARY ATIENO to your account ACME-T001. Ref CO123456AB. Thank you.",
     100),
    ("NCBA credit", "NCBA",
     "{*}credited with KES {amount} on {*} from {name}. Ref {ref}{*}",
     "Your account has been credited with KES 4,000.00 on 22/07 from JOHN KAMAU. Ref NC789012CD available balance KES 9,000.",
     100),
    ("Absa credit", "ABSA",
     "{*}received KES {amount} from {name} to account {account}. Ref {ref}{*}",
     "Absa: You have received KES 6,300.00 from PETER O to account ACME-T003. Ref AB456789EF on 22/07/2026.",
     100),
    ("Family Bank credit", "FAMILY BANK",
     "{*}KES {amount} received from {name} to your account {account}, Ref {ref}{*}",
     "FamilyBank: KES 1,200.00 received from GRACE W to your account ACME-T004, Ref FB321654GH. Bal KES 3,000.",
     100),
    ("DTB credit", "DTB",
     "{*}received KES {amount} from {name}. Ref {ref}{*}",
     "DTB: You have received KES 7,700.00 from BRIAN K. Ref DT147258IJ. Thank you for banking with DTB.",
     100),
    ("Stanbic credit", "STANBIC",
     "{*}credited KES {amount} from {name}. Ref {ref}{*}",
     "Stanbic: Your account credited KES 5,500.00 from AMINA H. Ref ST963852KL on 22 Jul.",
     100),
    ("I&M credit", "I&M",
     "{*}received KES {amount} from {name} to your account {account} Ref {ref}{*}",
     "I&M Bank: received KES 8,800.00 from DIANA A to your account ACME-T005 Ref IM852741MN.",
     100),
    ("M-Pesa till (buy goods received)", "MPESA",
     "{ref} Confirmed. {*}Ksh{amount}{*}received from {name} {phone}{*}",
     "RJK5X9PLMN Confirmed. Ksh2,000.00 received from JAMES MWANGI 254711000001 for till on 22/7/26",
     95),
]


def upgrade():
    conn = op.get_bind()
    for name, sender_id, template_text, sample_text, priority in _PRESETS:
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM sms_parser_templates WHERE name = %s AND sender_id = %s LIMIT 1",
            (name, sender_id),
        ).first()
        if exists:
            continue
        conn.exec_driver_sql(
            "INSERT INTO sms_parser_templates "
            "(name, sender_id, template_text, sample_text, is_active, priority, created_at) "
            "VALUES (%s, %s, %s, %s, true, %s, now())",
            (name, sender_id, template_text, sample_text, priority),
        )


def downgrade():
    conn = op.get_bind()
    for name, sender_id, *_ in _PRESETS:
        conn.exec_driver_sql(
            "DELETE FROM sms_parser_templates WHERE name = %s AND sender_id = %s",
            (name, sender_id),
        )
