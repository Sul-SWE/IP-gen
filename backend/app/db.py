"""Database engine and sessions. MySQL in production, SQLite supported for quick local runs and tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _connect(dbapi_conn, _record):  # pragma: no cover - driver hook
            dbapi_conn.isolation_level = None      # we issue BEGIN ourselves
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        @event.listens_for(eng, "begin")
        def _begin(conn):  # pragma: no cover - driver hook
            conn.exec_driver_sql("BEGIN IMMEDIATE")  # one writer at a time, no lost updates

        return eng
    # READ COMMITTED: after taking the write lock every statement sees the newest committed data
    return create_engine(url, isolation_level="READ COMMITTED", pool_pre_ping=True, pool_recycle=1800)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def lock_writes(db: Session) -> None:
    """Serialise all writers: every state-changing transaction takes this row lock first.

    With it, 'check then insert' can never race with another request. UNIQUE constraints remain
    as a second line of defence.
    """
    from .models import Setting

    db.execute(select(Setting.value).where(Setting.name == "write_lock").with_for_update()).first()


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
