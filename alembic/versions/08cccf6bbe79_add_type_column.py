"""Add type column

Revision ID: 08cccf6bbe79
Revises: 2de57fa5e865
Create Date: 2022-06-24 20:03:43.180492

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "08cccf6bbe79"
down_revision = "2de57fa5e865"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat",
        sa.Column(
            "type",
            sa.String(),
            nullable=False,
            server_default="private",
        ),
    )


def downgrade():
    op.drop_column("chat", "type")
