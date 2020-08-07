"""

Revision ID: 0309_add_sinch
Revises: 0308_add_email_parameters
Create Date: 2020-07-29 12:00:00

"""
from alembic import op
import uuid


revision = '0309_add_sinch'
down_revision = '0308_add_email_parameters'

id = uuid.uuid4()


def upgrade():
    op.execute(f"""
        INSERT INTO provider_details (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Sinch SMS', 'sinch', 5, 'sms', true, 1)
    """)
    op.execute(f"""
        INSERT INTO provider_details_history (id, display_name, identifier, priority, notification_type, active, version) 
        VALUES ('{id}', 'Sinch SMS', 'sinch', 5, 'sms', true, 1)
    """)


def downgrade():
    op.execute("DELETE FROM provider_details WHERE identifier = 'sinch'")
    op.execute("DELETE FROM provider_details_history WHERE identifier = 'sinch'")
