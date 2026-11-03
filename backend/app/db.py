"""SQLite engine for ``DATA_DIR/app.db`` (WAL mode, foreign keys on)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (register tables)

DB_NAME = "app.db"


def db_path(data_dir: Path) -> Path:
    return data_dir / DB_NAME


def make_engine(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path(data_dir)}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    SQLModel.metadata.create_all(engine)
    from app.extract.index import FTS_DDL

    with engine.begin() as conn:
        conn.exec_driver_sql(FTS_DDL)
    return engine


def session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def snapshot(data_dir: Path, dest: Path) -> Path:
    """Write a consistent copy of the live database (for backups) using SQLite's backup API."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(db_path(data_dir))
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    tmp.replace(dest)
    return dest
