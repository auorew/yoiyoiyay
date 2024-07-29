"""Add tiktok slideshow mode to Chat

Revision ID: 5ce2b4762b09
Revises: f00d3e4ac90e
Create Date: 2023-10-22 02:26:15.787166

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "5ce2b4762b09"
down_revision = "f00d3e4ac90e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat",
        sa.Column(
            "tt_slide_mode",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade():
    op.drop_column("chat", "tt_slide_mode")
