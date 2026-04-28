"""Alembic environment.

Revision *filenames* (timestamp prefix, etc.) are controlled by ``file_template`` in
``alembic.ini``, not in this file. Alembic supplies ``year``, ``month``, ``day``,
``hour``, ``minute``, ``second``, ``epoch``, ``rev``, and ``slug`` placeholders.
"""

from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import engine_from_config, pool

from alembic import context

# Project root on sys.path (alembic.ini prepend_sys_path = .)
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.core.config import settings
from src.db.base import Base
import src.db.models  # noqa: F401 — register mappers

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_database_url() -> str:
    """Alembic uses a sync driver; strip asyncpg from the app URL."""
    url = str(settings.DATABASE_URL)
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if "+asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = get_sync_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
