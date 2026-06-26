"""history/schema.py: Shared history-table schema and pragmas.

Both :class:`ConversionDB` and :class:`DBWriteQueue` write to the same
``history`` table, so they share the ``CREATE TABLE`` statement and WAL
pragmas from here.
"""

import sqlite3


CREATE_HISTORY_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS history ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    source_path TEXT,"
    "    dest_path TEXT,"
    "    job_type TEXT,"
    "    command TEXT,"
    "    status TEXT,"
    "    error_msg TEXT,"
    "    stdout TEXT,"
    "    timestamp TEXT,"
    "    UNIQUE(source_path, dest_path)"
    ")"
)


INSERT_OR_REPLACE_HISTORY_SQL = (
    "INSERT OR REPLACE INTO history "
    "  (source_path, dest_path, job_type, command, status, error_msg, stdout, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def apply_history_pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL mode and busy-timeout on the given connection.

    Called by both ``ConversionDB.__init__`` and ``DBWriteQueue._writer_loop``
    so the runtime characteristics match regardless of which class opens the DB.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
