"""Alembic environment"""

import logging
import os
import sys

from logging.config import fileConfig
from typing import Optional

# sqlalchemy
from sqlalchemy import engine_from_config, pool

# sqlalchemy typing
from sqlalchemy.sql.schema import Column, Table

# alembic context
from alembic import context

# import connection URI
from yoiyoi.db import DB_URI

# get sqlalchemy declarative base
from yoiyoi.db.models import Base

VERSION_TABLE = "yoiyoi_alembic"

# get alembic migrations logger
log = logging.getLogger("alembic.runtime.migration")

# get parent directory
sys.path.append(os.path.abspath(os.getcwd()))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
CONFIG = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(CONFIG.config_file_name)

# change database URI
CONFIG.set_main_option("sqlalchemy.url", DB_URI)

# models MetaData
TARGET_METADATA = Base.metadata


# do not drop tables if unknown to alembic
def include_object(
    obj: Table | Column,
    name: str,
    type_: str,
    reflected: bool,
    compare_to: Optional[Table | Column],
):
    if type_ == "table" and reflected and compare_to is None:
        log.info(
            "Exclude: %s [%s, %s] %s | %s.",
            obj,
            name,
            type_,
            reflected,
            compare_to,
        )
        return False
    else:
        log.info(
            "Include: %s [%s, %s] %s | %s.",
            obj,
            name,
            type_,
            reflected,
            compare_to,
        )
        return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = CONFIG.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=TARGET_METADATA,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        CONFIG.get_section(CONFIG.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=TARGET_METADATA,
            version_table=VERSION_TABLE,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
