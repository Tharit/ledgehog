"""Alembic environment. The connection is handed in by app.utils.db.migrate (or, for the
`alembic` CLI, built from the environment). No autogenerate: there is no metadata."""

from alembic import context
from sqlalchemy import Connection

from app.utils.config import Config
from app.utils.db.engine import make_engine

config = context.config


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    engine = make_engine(Config.from_env(), pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            _run(conn)
    finally:
        engine.dispose()
