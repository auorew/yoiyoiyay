"""Change chat.last_info type to json

Revision ID: 56328f432855
Revises: b5115239219d
Create Date: 2022-10-22 17:31:33.207331

"""
import sqlalchemy as sa

from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "56328f432855"
down_revision = "b5115239219d"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        table_name="chat",
        column_name="last_info",
        type_=JSONB(),
        postgresql_using="last_info::jsonb",
    )


def downgrade():
    op.alter_column(
        table_name="chat",
        column_name="last_info",
        type_=sa.String(),
        postgresql_using="last_info::jsonb",
    )
