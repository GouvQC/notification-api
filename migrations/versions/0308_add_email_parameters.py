"""

Revision ID: 0308_add_email_parameters
Revises: 0306c_branding_organisation
Create Date: 2020-07-23 10:00:00

"""
from alembic import op


revision = '0308_add_email_parameters'
down_revision = '0306c_branding_organisation'


def upgrade():
    op.execute('ALTER TABLE notifications ADD COLUMN additional_email_parameters jsonb')
    op.execute('ALTER TABLE notification_history ADD COLUMN additional_email_parameters jsonb')

def downgrade():
    op.execute('ALTER TABLE notifications DROP COLUMN additional_email_parameters')
    op.execute('ALTER TABLE notification_history DROP COLUMN additional_email_parameters')
