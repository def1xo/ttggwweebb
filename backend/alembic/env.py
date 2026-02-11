import os
import time
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.exc import OperationalError

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

# Import models so Base.metadata is populated
from app.db.base import Base  # noqa: E402
import app.db.models  # noqa: F401,E402

target_metadata = Base.metadata


def get_url() -> str:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URI")
        or config.get_main_option("sqlalchemy.url")
    )


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    # Docker compose run may start DB container but Postgres can still be warming up.
    # Retry connection a few times to avoid transient "connection refused" failures.
    retries = int(os.getenv("ALEMBIC_DB_CONNECT_RETRIES", "30"))
    delay_s = float(os.getenv("ALEMBIC_DB_CONNECT_DELAY", "1"))
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            with connectable.connect() as connection:
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    compare_type=True,
                )

                with context.begin_transaction():
                    context.run_migrations()
                return
        except OperationalError as exc:
            last_error = exc
            if attempt >= retries:
                raise
            print(f"[alembic] DB is not ready yet (attempt {attempt}/{retries}), retrying in {delay_s:.1f}s...")
            time.sleep(delay_s)

    if last_error:
        raise last_error


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
