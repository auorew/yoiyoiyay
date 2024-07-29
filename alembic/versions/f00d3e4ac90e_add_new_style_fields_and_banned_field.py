"""Add new style fields and banned field

Revision ID: f00d3e4ac90e
Revises: e35bf5f50d2f
Create Date: 2023-06-12 07:07:12.128530

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f00d3e4ac90e"
down_revision = "e35bf5f50d2f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat",
        sa.Column(
            "tt_style",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "in_style",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "yts_orig",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "yts_style",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "is_banned",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("chat", sa.Column("banned_for", sa.String(), nullable=True))


def downgrade():
    op.drop_column("chat", "banned_for")
    op.drop_column("chat", "is_banned")
    op.drop_column("chat", "yts_style")
    op.drop_column("chat", "yts_orig")
    op.drop_column("chat", "in_style")
    op.drop_column("chat", "tt_style")
