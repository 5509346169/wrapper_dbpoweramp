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
    "    file_size INTEGER,"
    "    verify_status TEXT,"
    "    verify_reason TEXT,"
    "    verify_format TEXT,"
    "    verify_duration_s REAL,"
    "    UNIQUE(source_path, dest_path)"
    ")"
)

# Idempotent migration for existing databases that predate the verify columns.
ADD_VERIFY_COLUMNS_SQL = (
    "ALTER TABLE history ADD COLUMN verify_status TEXT;"
    "ALTER TABLE history ADD COLUMN verify_reason TEXT;"
    "ALTER TABLE history ADD COLUMN verify_format TEXT;"
    "ALTER TABLE history ADD COLUMN verify_duration_s REAL;"
)

# Idempotent migration for existing databases that predate the file_size column.
ADD_FILE_SIZE_COLUMN_SQL = (
    "ALTER TABLE history ADD COLUMN file_size INTEGER"
)

# Idempotent migration: add temp_filename for staging debug.
ADD_TEMP_FILENAME_COLUMN_SQL = (
    "ALTER TABLE history ADD COLUMN temp_filename TEXT"
)


INSERT_OR_REPLACE_HISTORY_SQL = (
    "INSERT OR REPLACE INTO history "
    "  (source_path, dest_path, job_type, command, status, error_msg, stdout, timestamp, file_size, "
    "   verify_status, verify_reason, verify_format, verify_duration_s, temp_filename) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def apply_history_pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL mode and busy-timeout on the given connection.

    Called by both ``ConversionDB.__init__`` and ``DBWriteQueue._writer_loop``
    so the runtime characteristics match regardless of which class opens the DB.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
