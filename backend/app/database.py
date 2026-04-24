from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from backend.app.config import settings

logger = logging.getLogger(__name__)


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS platforms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id TEXT NOT NULL,
        station_name TEXT NOT NULL,
        line_id TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        UNIQUE(station_id, line_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ride_edges (
        from_platform INTEGER NOT NULL REFERENCES platforms(id),
        to_platform   INTEGER NOT NULL REFERENCES platforms(id),
        travel_time_s REAL NOT NULL,
        line_id TEXT NOT NULL,
        PRIMARY KEY(from_platform, to_platform)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transfer_edges (
        from_platform INTEGER NOT NULL REFERENCES platforms(id),
        to_platform   INTEGER NOT NULL REFERENCES platforms(id),
        transfer_time_s REAL NOT NULL DEFAULT 180,
        PRIMARY KEY(from_platform, to_platform)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS walk_nodes (
        id INTEGER PRIMARY KEY,
        lat REAL NOT NULL,
        lng REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS walk_edges (
        from_node INTEGER NOT NULL REFERENCES walk_nodes(id),
        to_node   INTEGER NOT NULL REFERENCES walk_nodes(id),
        travel_time_s REAL NOT NULL,
        PRIMARY KEY(from_node, to_node)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entrance_edges (
        platform_id INTEGER NOT NULL REFERENCES platforms(id),
        walk_node_id INTEGER NOT NULL REFERENCES walk_nodes(id),
        travel_time_s REAL NOT NULL,
        PRIMARY KEY(platform_id, walk_node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


@contextmanager
def get_db_connection() -> Iterator[sqlite3.Connection]:
    db_path = settings.db_path_resolved
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_tables() -> None:
    with get_db_connection() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
    logger.info("Database schema initialized at %s", settings.db_path_resolved)
