"""add sms_credit_ranges table

Revision ID: 5435e6002fe8
Revises: fd0e10981cd2
Create Date: 2026-07-23 01:52:33.658441

Scoped to the new sms_credit_ranges table only — the autogenerate run also
surfaced unrelated pre-existing drift, deliberately excluded.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5435e6002fe8'
down_revision = 'fd0e10981cd2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sms_credit_ranges',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('min_words', sa.Integer(), nullable=False),
        sa.Column('max_words', sa.Integer(), nullable=True),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('sms_credit_ranges', schema=None) as batch_op:
        batch_op.create_index('ix_sms_credit_ranges_min', ['min_words'], unique=False)


def downgrade():
    with op.batch_alter_table('sms_credit_ranges', schema=None) as batch_op:
        batch_op.drop_index('ix_sms_credit_ranges_min')
    op.drop_table('sms_credit_ranges')
