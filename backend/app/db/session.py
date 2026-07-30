from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


def enforce_sqlite_foreign_keys(target: Engine) -> Engine:
    """Turn on foreign-key enforcement for SQLite connections.

    SQLite ships with ``PRAGMA foreign_keys=OFF``, so a referential bug that PostgreSQL
    rejects outright passes silently in local development and in a SQLite test run. That
    divergence is worse than either behaviour on its own: it means the cheap, fast test
    environment is *weaker* than production and will not catch the class of bug it is
    most likely to introduce.

    No-op for any other dialect, which enforces keys already.
    """
    if not target.url.get_backend_name().startswith("sqlite"):
        return target

    @event.listens_for(target, "connect")
    def _set_pragma(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return target


engine = enforce_sqlite_foreign_keys(
    create_engine(
        settings.database_url,
        connect_args=(
            {"check_same_thread": False} if "sqlite" in settings.database_url else {}
        ),
    )
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
