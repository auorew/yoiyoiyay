"""Add column px_style to Chat and update tw_style

Revision ID: e35bf5f50d2f
Revises: 04ffaa1fe4a6
Create Date: 2022-11-22 08:18:29.449992

"""
import sqlalchemy as sa

from sqlalchemy import orm, select

from alembic import op

# revision identifiers, used by Alembic.
revision = "e35bf5f50d2f"
down_revision = "04ffaa1fe4a6"
branch_labels = None
depends_on = None

Chat = sa.sql.table(
    "chat",
    sa.sql.column("id", sa.BigInteger),
    sa.sql.column("tw_style", sa.Integer),
)


def upgrade():
    with orm.Session(bind=op.get_bind()) as session:
        for chat in session.execute(select(Chat)):
            if chat.tw_style > 0:
                op.execute(
                    Chat.update()
                    .where(Chat.c.id == chat.id)
                    .values(tw_style=chat.tw_style + 1)
                )

    op.add_column(
        "chat",
        sa.Column(
            "px_orig",
            sa.Boolean(),
            nullable=False,
            server_default=sa.sql.false(),
        ),
    )
    op.add_column(
        "chat",
        sa.Column(
            "px_style",
            sa.Integer(),
            nullable=False,
            server_default=sa.sql.text("3"),
        ),
    )


def downgrade():
    with orm.Session(bind=op.get_bind()) as session:
        for chat in session.execute(select(Chat)):
            if chat.tw_style > 1:
                op.execute(
                    Chat.update()
                    .where(Chat.c.id == chat.id)
                    .values(tw_style=chat.tw_style - 1)
                )

    op.drop_column("chat", "px_orig")
    op.drop_column("chat", "px_style")
