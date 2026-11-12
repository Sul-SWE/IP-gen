"""Alembic environment: uses the same DATABASE_URL as the application."""

from alembic import context

from app.config import load_settings
from app.db import make_engine
from app.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = context.config.attributes.get("engine") or make_engine(load_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
