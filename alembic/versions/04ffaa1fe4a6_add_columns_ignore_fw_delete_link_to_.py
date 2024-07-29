"""Add columns ignore_fw, delete_link to Chat

Revision ID: 04ffaa1fe4a6
Revises: 56328f432855
Create Date: 2022-11-17 04:19:13.490318

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "04ffaa1fe4a6"
down_revision = "56328f432855"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat",
        sa.Column(
            "ignore_fw",
            sa.Boolean(),
            nullable=False,
            server_default=sa.sql.false(),
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "delete_link",
            sa.Boolean(),
            nullable=False,
            server_default=sa.sql.false(),
        ),
    )


def downgrade():
    op.drop_column("chat", "delete_link")
    op.drop_column("chat", "ignore_fw")
