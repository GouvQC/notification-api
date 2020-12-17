"""

Revision ID: 0310c_add_shortnumber
Revises: 0310b_add_sagir_code
Create Date: 2020-12-15 13:33:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0310c_add_shortnumber_keyword'
down_revision = '0310b_add_sagir_code'


def upgrade():
    op.create_table(
        'inbound_sms_keyword',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('content', sa.String, nullable=False),
        sa.Column('notify_short_number', sa.String, nullable=False),
        sa.Column('user_number', sa.String, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('provider_date', sa.DateTime, nullable=True),
        sa.Column('provider_reference', sa.String, nullable=True),
        sa.Column('provider', sa.String, nullable=False),

        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inbound_sms_keyword_service_id'), 'inbound_sms_keyword', ['service_id'], unique=False)
    op.create_index(op.f('ix_inbound_sms_keyword_user_number'), 'inbound_sms_keyword', ['user_number'], unique=False)

    op.create_table('inbound_shortnumbers',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('short_number', sa.String(length=11), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('short_number')
    )
    op.create_index(op.f('ix_inbound_shortnumbers_service_id'), 'inbound_shortnumbers', ['service_id'], unique=True)

    op.execute("INSERT INTO service_permission_types (name) VALUES ('inbound_sms_keyword')")

def downgrade():
    op.drop_table('inbound_sms_keyword')
    op.drop_table('inbound_shortnumbers')

    op.execute("DELETE FROM service_permission_types WHERE name = 'inbound_sms_keyword'")
    