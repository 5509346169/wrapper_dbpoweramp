"""Index package for tracking file-level copy/sync operations."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from src.index.schema import (
    CREATE_INDEX_ENTRIES_TABLE_SQL,
    INSERT_INDEX_ENTRY_SQL,
    apply_index_pragmas,
    ensure_is_lossy_column,
)

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

    # Auto-flush the buffered batch every N rows to bound memory and latency.
    _BATCH_SIZE = 1000

    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the index_entries table exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute(CREATE_INDEX_ENTRIES_TABLE_SQL)
            # Migration: add is_lossy to tables created by older versions.
            ensure_is_lossy_column(self._conn)
            apply_index_pragmas(self._conn)
            self._conn.commit()

        self._pending: list[tuple] = []  # type: ignore[var-annotated]

    def add(self, row: IndexRow) -> None:
        """Buffer a single row; auto-flushes every ``_BATCH_SIZE`` rows.

        Args:
            row: IndexRow describing the file entry.
        """
        with self._lock:
            self._pending.append(
                (
                    row.source_path,
                    row.dest_path,
                    row.job_type,
                    row.file_size,
                    row.sidecar_files,
                    row.mtime,
                    None if row.is_lossy is None else int(row.is_lossy),
                    datetime.now(timezone.utc).isoformat(),
                )
            )
            if len(self._pending) >= self._BATCH_SIZE:
                self._flush_locked()

    def _flush_locked(self) -> None:
        """Internal: flush pending rows to the DB. Caller must hold ``_lock``."""
        if not self._pending:
            return
        self._conn.executemany(INSERT_INDEX_ENTRY_SQL, self._pending)
        self._conn.commit()
        self._pending.clear()

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
            self._conn.executemany(INSERT_INDEX_ENTRY_SQL, data)
            self._conn.commit()

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
        """Flush any buffered rows and commit the transaction to the database."""
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "IndexBuilder":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()
        self.close()

    @classmethod
    def from_existing(cls, db_path: Path) -> "IndexBuilder":
        """Open an existing index database (must exist).

        Args:
            db_path: Path to the existing SQLite database file.

        Returns:
            IndexBuilder instance connected to the existing database.

        Raises:
            FileNotFoundError: If the database file does not exist.
        """
        if not db_path.exists():
            raise FileNotFoundError(f"Index database not found: {db_path}")
        return cls(db_path)

    def get_summary(self) -> dict[str, int | dict[str, int]]:
        """Get a summary of the index contents.

        Returns:
            Dictionary with total count, lossy count, and counts by job_type.
        """
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM index_entries")
            total = cur.fetchone()[0]

            cur = self._conn.execute(
                "SELECT COUNT(*) FROM index_entries WHERE is_lossy = 1"
            )
            lossy_count = cur.fetchone()[0]

            cur = self._conn.execute(
                "SELECT job_type, COUNT(*) FROM index_entries GROUP BY job_type"
            )
            by_type = dict(cur.fetchall())

            cur = self._conn.execute("SELECT SUM(file_size) FROM index_entries")
            total_bytes = cur.fetchone()[0] or 0

        return {
            "total": total,
            "lossy": lossy_count,
            "by_type": by_type,
            "total_bytes": total_bytes,
        }
