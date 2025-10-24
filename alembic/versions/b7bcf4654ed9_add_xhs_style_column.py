"""Add xhs style column

Revision ID: b7bcf4654ed9
Revises: 5ce2b4762b09
Create Date: 2025-10-24 06:01:47.030472

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7bcf4654ed9"
down_revision = "5ce2b4762b09"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat",
        sa.Column(
            "xhs_orig",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "xhs_style",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )


def downgrade():
    op.drop_column("chat", "xhs_style")
    op.drop_column("chat", "xhs_orig")
