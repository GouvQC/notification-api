"""

Revision ID: 0310a_drop_emailparam
Revises: 0310_account_change_type
Create Date: 2020-07-23 10:00:00

"""
from alembic import op


revision = '0310a_drop_emailparam'
down_revision = '0310_account_change_type'


def upgrade():
    op.execute('ALTER TABLE notification_history DROP COLUMN additional_email_parameters')

def downgrade():
    op.execute('ALTER TABLE notification_history ADD COLUMN additional_email_parameters jsonb')
