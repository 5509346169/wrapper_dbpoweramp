"""index/schema.py: Shared index_entries table schema and pragmas.

Extracted from ``src.index.builder.IndexBuilder`` so the schema lives in one
place and can be referenced from migrations or tests without importing the
class.
"""

import sqlite3


CREATE_INDEX_ENTRIES_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS index_entries ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    source_path TEXT NOT NULL,"
    "    dest_path TEXT NOT NULL,"
    "    job_type TEXT NOT NULL,"
    "    file_size INTEGER NOT NULL,"
    "    sidecar_files TEXT NOT NULL,"
    "    mtime REAL NOT NULL,"
    "    is_lossy INTEGER,"
    "    created_at TEXT NOT NULL"
    ")"
)


INSERT_INDEX_ENTRY_SQL = (
    "INSERT INTO index_entries "
    "(source_path, dest_path, job_type, file_size, sidecar_files, mtime, is_lossy, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


IS_LOSSY_COLUMN_MIGRATION = (
    "ALTER TABLE index_entries ADD COLUMN is_lossy INTEGER"
)


def apply_index_pragmas(conn: sqlite3.Connection) -> None:
    """Set pragmas that speed up bulk inserts on Windows / network drives."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def ensure_is_lossy_column(conn: sqlite3.Connection) -> None:
    """Migration: add ``is_lossy`` to tables created by older versions."""
    cur = conn.execute("PRAGMA table_info(index_entries)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "is_lossy" not in existing_cols:
        conn.execute(IS_LOSSY_COLUMN_MIGRATION)
