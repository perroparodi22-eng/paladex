"""SQLite engine / session management."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _configure_sqlite(dbapi_conn, _record):  # pragma: no cover - trivial
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # readers never block the collector
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None or url is not None:
        url = url or get_settings().database_url
        engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _configure_sqlite)
        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db(url: str | None = None) -> Engine:
    from . import models  # noqa: F401  (register tables)
    from .reference.seed import seed_reference_data

    engine = get_engine(url)
    Base.metadata.create_all(engine)
    migrate_add_missing_columns(engine)
    with session_scope() as s:
        seed_reference_data(s)
    return engine


def migrate_add_missing_columns(engine: Engine) -> list[str]:
    """Lightweight forward migration for SQLite: add columns that exist in the models but not
    in an older database file (new optional columns only — never drops or alters data).

    New columns must therefore be nullable or have a server-side default. Returns the list of
    "table.column" added (for logging/tests).
    """
    from sqlalchemy import inspect, text

    added: list[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = ""
                if not col.nullable:
                    # SQLite requires a default for NOT NULL columns added later
                    py_default = getattr(col.default, "arg", None)
                    if isinstance(py_default, bool):
                        default = f" DEFAULT {int(py_default)}"
                    elif isinstance(py_default, (int, float)):
                        default = f" DEFAULT {py_default}"
                    elif isinstance(py_default, str):
                        default = " DEFAULT '" + py_default.replace("'", "''") + "'"
                    else:
                        default = " DEFAULT NULL"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}{default}'))
                added.append(f"{table.name}.{col.name}")
    if added:
        import logging

        logging.getLogger(__name__).info("database migrated: added columns %s", ", ".join(added))
    return added
