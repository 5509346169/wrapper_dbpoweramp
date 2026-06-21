"""Index package for tracking file-level copy/sync operations."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

try:
    from src.index.scanner import IndexRow
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class IndexRow:
        source_path: str
        dest_path: str
        job_type: str
        file_size: int
        sidecar_files: str
        mtime: float
        is_lossy: Optional[bool] = None


class IndexBuilder:
    """Manages the index_entries table for tracking file copies and syncs.

    Mirrors the pattern of history.db.ConversionDB.
    """

    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the index_entries table exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute(
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
            # Migration: add is_lossy to tables created by older versions.
            try:
                self._conn.execute("ALTER TABLE index_entries ADD COLUMN is_lossy INTEGER")
            except sqlite3.OperationalError:
                # Column already exists — nothing to do.
                pass
            self._conn.commit()

    def add(self, row: IndexRow) -> None:
        """Insert a single row into the index.

        Args:
            row: IndexRow describing the file entry.
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO index_entries "
                "(source_path, dest_path, job_type, file_size, sidecar_files, mtime, is_lossy, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.source_path,
                    row.dest_path,
                    row.job_type,
                    row.file_size,
                    row.sidecar_files,
                    row.mtime,
                    None if row.is_lossy is None else int(row.is_lossy),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def add_many(self, rows: list[IndexRow]) -> None:
        """Insert multiple rows into the index using executemany.

        Args:
            rows: List of IndexRow objects.
        """
        if not rows:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        data = [
            (
                row.source_path,
                row.dest_path,
                row.job_type,
                row.file_size,
                row.sidecar_files,
                row.mtime,
                None if row.is_lossy is None else int(row.is_lossy),
                timestamp,
            )
            for row in rows
        ]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO index_entries "
                "(source_path, dest_path, job_type, file_size, sidecar_files, mtime, is_lossy, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                data,
            )

    def iter_rows(self) -> Iterator[IndexRow]:
        """Yield all rows in insertion order (id ASC)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT source_path, dest_path, job_type, file_size, sidecar_files, mtime, is_lossy "
                "FROM index_entries ORDER BY id"
            )
            rows = cur.fetchall()
        for row in rows:
            yield IndexRow(
                source_path=row[0],
                dest_path=row[1],
                job_type=row[2],
                file_size=row[3],
                sidecar_files=row[4],
                mtime=row[5],
                is_lossy=None if row[6] is None else bool(row[6]),
            )

    def commit(self) -> None:
        """Commit any pending transaction to the database."""
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "IndexBuilder":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()
        self.close()
