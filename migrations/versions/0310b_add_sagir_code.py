"""

Revision ID: 0310b_add_sagir_code
Revises: 0310a_drop_emailparam
Create Date: 2020-11-26 9:45:00

"""
from alembic import op


revision = '0310b_add_sagir_code'
down_revision = '0310a_drop_emailparam'


def upgrade():
    op.execute('ALTER TABLE organisation ADD COLUMN sagir_code VARCHAR(255)')

def downgrade():
    op.execute('ALTER TABLE organisation DROP COLUMN sagir_code')
    