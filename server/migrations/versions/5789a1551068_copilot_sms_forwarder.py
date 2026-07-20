"""Co-pilot SMS forwarder — devices, parser templates, ingest log, app releases

Purely ADDITIVE. Introduces copilot_devices / sms_parser_templates /
copilot_messages / copilot_app_releases, plus four columns on
landlord_settings (copilot_enabled, copilot_auto_allocate,
copilot_consented_at, copilot_admin_locked). See COPILOT_PLATFORM_SPEC.md §2/§10.

Revision ID: 5789a1551068
Revises: 3743a24840d5
Create Date: 2026-07-07 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5789a1551068'
down_revision = '3743a24840d5'
branch_labels = None
depends_on = None


def upgrade():
    # 1) landlord_settings additions ------------------------------------------
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('copilot_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('copilot_auto_allocate', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('copilot_consented_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('copilot_admin_locked', sa.Boolean(), nullable=False, server_default=sa.false()))

    # 2) copilot_devices --------------------------------------------------------
    op.create_table(
        'copilot_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('device_name', sa.String(length=100), nullable=False),
        sa.Column('device_model', sa.String(length=100), nullable=True),
        sa.Column('app_version', sa.String(length=20), nullable=True),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='active'),
        sa.Column('sender_ids', sa.Text(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_copilot_devices_token_hash'),
    )
    op.create_index(op.f('ix_copilot_devices_landlord_id'), 'copilot_devices', ['landlord_id'], unique=False)
    op.create_index(op.f('ix_copilot_devices_token_hash'), 'copilot_devices', ['token_hash'], unique=False)

    # 3) sms_parser_templates -----------------------------------------------------
    op.create_table(
        'sms_parser_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('sender_id', sa.String(length=30), nullable=False),
        sa.Column('template_text', sa.Text(), nullable=False),
        sa.Column('sample_text', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sms_parser_templates_sender_id'), 'sms_parser_templates', ['sender_id'], unique=False)

    # 4) copilot_messages ----------------------------------------------------------
    op.create_table(
        'copilot_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('landlord_id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('client_uuid', sa.String(length=40), nullable=False),
        sa.Column('sender_id', sa.String(length=30), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=False),
        sa.Column('sms_received_at', sa.DateTime(), nullable=True),
        sa.Column('dedupe_hash', sa.String(length=64), nullable=False),
        sa.Column('parse_status', sa.String(length=12), nullable=False),
        sa.Column('match_status', sa.String(length=12), nullable=False, server_default='n_a'),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('parsed_ref', sa.String(length=40), nullable=True),
        sa.Column('parsed_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('parsed_name', sa.String(length=120), nullable=True),
        sa.Column('parsed_account', sa.String(length=50), nullable=True),
        sa.Column('parsed_phone', sa.String(length=20), nullable=True),
        sa.Column('error_reason', sa.String(length=255), nullable=True),
        sa.Column('tenant_id', sa.Integer(), nullable=True),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('mpesa_transaction_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['landlord_id'], ['landlords.id'], ),
        sa.ForeignKeyConstraint(['device_id'], ['copilot_devices.id'], ),
        sa.ForeignKeyConstraint(['template_id'], ['sms_parser_templates.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ),
        sa.ForeignKeyConstraint(['mpesa_transaction_id'], ['mpesa_transactions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'client_uuid', name='uq_copilot_messages_device_uuid'),
    )
    op.create_index(op.f('ix_copilot_messages_landlord_id'), 'copilot_messages', ['landlord_id'], unique=False)
    op.create_index(op.f('ix_copilot_messages_device_id'), 'copilot_messages', ['device_id'], unique=False)
    op.create_index(op.f('ix_copilot_messages_sender_id'), 'copilot_messages', ['sender_id'], unique=False)
    op.create_index(op.f('ix_copilot_messages_dedupe_hash'), 'copilot_messages', ['dedupe_hash'], unique=False)
    op.create_index(op.f('ix_copilot_messages_parsed_ref'), 'copilot_messages', ['parsed_ref'], unique=False)
    op.create_index(op.f('ix_copilot_messages_tenant_id'), 'copilot_messages', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_copilot_messages_payment_id'), 'copilot_messages', ['payment_id'], unique=False)

    # 5) copilot_app_releases --------------------------------------------------------
    op.create_table(
        'copilot_app_releases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('version_name', sa.String(length=20), nullable=False),
        sa.Column('version_code', sa.Integer(), nullable=False),
        sa.Column('apk_path', sa.String(length=255), nullable=False),
        sa.Column('release_notes', sa.Text(), nullable=True),
        sa.Column('is_latest', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('min_supported_version_code', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version_code', name='uq_copilot_app_releases_version_code'),
    )

    # 6) seed known-format parser templates (COPILOT_PLATFORM_SPEC.md §3.2) --------
    op.execute(
        "INSERT INTO sms_parser_templates "
        "(name, sender_id, template_text, sample_text, is_active, priority, created_at) VALUES "
        "('M-Pesa C2B (received from)', 'MPESA', "
        "'{ref} Confirmed. {*}Ksh{amount} received from {name} {phone} on {*}', "
        "'QCA1B2C3D4 Confirmed. Ksh1,500.00 received from JOHN DOE 254712345678 on 1/6/25 at 10:34 AM', "
        "true, 100, now()), "
        "('M-Pesa paybill with account', 'MPESA', "
        "'{ref} Confirmed.{*}Ksh{amount}{*}received from {name} {phone}{*}for account {account}{*}', "
        "'QCA1B2C3D5 Confirmed. Ksh1,500.00 received from JOHN DOE 254712345678 for account A12 on 1/6/25 at 10:34 AM', "
        "true, 90, now()), "
        "('KCB credit alert', 'KCB', "
        "'{*}KES {amount} received from {name} to your account {account}, Ref {ref}{*}', "
        "'Dear Customer, KES 15,000.00 received from JANE WANJIKU to your account A12, Ref FT2312345678 on 01-06-2025.', "
        "true, 100, now()), "
        "('Equity credit alert', 'EQUITY BANK', "
        "'{*}received KES {amount} from {name}. Ref: {ref}{*}', "
        "'You have received KES 10,000.00 from PETER OTIENO. Ref: EQ12345678. Available balance is KES 25,000.00.', "
        "true, 100, now())"
    )


def downgrade():
    op.drop_table('copilot_app_releases')
    op.drop_index(op.f('ix_copilot_messages_payment_id'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_tenant_id'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_parsed_ref'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_dedupe_hash'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_sender_id'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_device_id'), table_name='copilot_messages')
    op.drop_index(op.f('ix_copilot_messages_landlord_id'), table_name='copilot_messages')
    op.drop_table('copilot_messages')
    op.drop_index(op.f('ix_sms_parser_templates_sender_id'), table_name='sms_parser_templates')
    op.drop_table('sms_parser_templates')
    op.drop_index(op.f('ix_copilot_devices_token_hash'), table_name='copilot_devices')
    op.drop_index(op.f('ix_copilot_devices_landlord_id'), table_name='copilot_devices')
    op.drop_table('copilot_devices')
    with op.batch_alter_table('landlord_settings', schema=None) as batch_op:
        batch_op.drop_column('copilot_admin_locked')
        batch_op.drop_column('copilot_consented_at')
        batch_op.drop_column('copilot_auto_allocate')
        batch_op.drop_column('copilot_enabled')
