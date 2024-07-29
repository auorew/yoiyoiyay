"""Database module"""

# sqlalchemy modules
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# settings
from yoiyoi.extra.settings import bot_settings

# database connection string
DB_URI = bot_settings.database_url

# engine settings
ENGINE = create_engine(DB_URI, pool_pre_ping=True)

# session factory
Session = sessionmaker(ENGINE)


# base class for declarative class definitions
class Base(DeclarativeBase):
    pass
