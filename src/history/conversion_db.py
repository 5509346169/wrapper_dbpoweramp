"""history/conversion_db.py: Synchronous wrapper for conversion/copy history.

Provides resume-check semantics: a job is skippable only if a matching
``(source_path, dest_path, job_type)`` row exists with status=SUCCESS and the
destination file still exists on disk.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from src.history.schema import (
    ADD_FILE_SIZE_COLUMN_SQL,
    ADD_VERIFY_COLUMNS_SQL,
    CREATE_HISTORY_TABLE_SQL,
    INSERT_OR_REPLACE_HISTORY_SQL,
    apply_history_pragmas,
)
from src.history.migrations import migrate_to_current
from rich import print as rprint


class ConversionDB:
    """Wraps a SQLite connection for tracking conversion/copy history."""

    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection, auto-migrate, and ensure the history table exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        apply_history_pragmas(self._conn)
        self._lock = threading.RLock()
        with self._lock:
            # Auto-migrate to the latest schema version.
            try:
                result = migrate_to_current(db_path)
                for msg in result.messages:
                    rprint(f"[cyan][migration][/cyan] {msg}")
            except Exception as exc:
                # Fall back to backup on migration failure (migrate_to_current
                # restores the backup before raising, but we surface the error).
                raise RuntimeError(
                    f"Schema migration failed and was rolled back: {exc}"
                ) from exc

            self._conn.execute(CREATE_HISTORY_TABLE_SQL)
            self._conn.commit()
            # Idempotent migration: column may already exist on existing databases.
            try:
                self._conn.execute(ADD_FILE_SIZE_COLUMN_SQL)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
            # Idempotent migration: verify columns may already exist.
            try:
                for stmt in ADD_VERIFY_COLUMNS_SQL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        self._conn.execute(stmt)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # columns already exist

    def get_record(self, source: str, dest: str) -> Optional[dict]:
        """Return the row matching (source_path, dest_path), or None.

        Args:
            source: Source file path.
            dest: Destination file path.

        Returns:
            Dict with columns: id, source_path, dest_path, job_type, command,
            status, error_msg, stdout, timestamp, file_size, verify_status,
            verify_reason, verify_format, verify_duration_s. Or None if no row exists.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, source_path, dest_path, job_type, command, status, "
                "       error_msg, stdout, timestamp, file_size, "
                "       verify_status, verify_reason, verify_format, verify_duration_s "
                "FROM history WHERE source_path = ? AND dest_path = ?",
                (source, dest),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "source_path": row[1],
                "dest_path": row[2],
                "job_type": row[3],
                "command": row[4],
                "status": row[5],
                "error_msg": row[6],
                "stdout": row[7],
                "timestamp": row[8],
                "file_size": row[9],
                "verify_status": row[10],
                "verify_reason": row[11],
                "verify_format": row[12],
                "verify_duration_s": row[13],
            }

    def log_conversion(
        self,
        source: str,
        dest: str,
        job_type: str,
        command: Optional[str],
        status: str,
        error_msg: Optional[str] = None,
        stdout: Optional[str] = None,
        file_size: Optional[int] = None,
        verify_status: Optional[str] = None,
        verify_reason: Optional[str] = None,
        verify_format: Optional[str] = None,
        verify_duration_s: Optional[float] = None,
    ) -> None:
        """Insert or update a history row with the current UTC timestamp.

        Uses INSERT OR REPLACE so re-logging a (source, dest) pair updates
        the existing row. The UNIQUE constraint on (source_path, dest_path)
        governs the replacement behavior.

        Args:
            source: Source file path.
            dest: Destination file path.
            job_type: 'convert' or 'copy'.
            command: The command string; may be None for job_type='copy'.
            status: JobStatus value (e.g. 'SUCCESS', 'FAILED', 'SKIPPED').
            error_msg: Optional error message for failed jobs.
            stdout: Optional captured stdout for the job.
            file_size: Optional file size in bytes of the output file.
            verify_status: Optional post-write verify status ('OK', 'NOT_OK', 'UNSUPPORTED').
            verify_reason: Optional human-readable verify reason.
            verify_format: Optional codec/container string (e.g. 'FLAC/PCM_16').
            verify_duration_s: Optional output duration in seconds.
        """
        with self._lock:
            timestamp = datetime_now_utc_iso()
            self._conn.execute(
                INSERT_OR_REPLACE_HISTORY_SQL,
                (
                    source, dest, job_type, command, status, error_msg, stdout,
                    timestamp, file_size,
                    verify_status, verify_reason, verify_format, verify_duration_s,
                ),
            )
            self._conn.commit()

    def should_skip(
        self, source: str, dest: str, job_type: str, dest_file_exists: bool,
        dest_file_size: Optional[int] = None,
    ) -> bool:
        """Decide whether to skip a job based on history.

        Returns True iff a row exists with matching (source_path, dest_path,
        job_type), the status is 'SUCCESS', AND dest_file_exists is True.

        A file previously logged as 'copy' but now requested as 'convert' will
        NOT be skipped — job_type must also match.

        NOTE: source-file mtime is NOT checked. A re-encode of an unchanged
        source file will be re-run even if a SUCCESS record already exists.
        This is a known limitation — the index tracks dest_path and job_type
        match but not the source's modification time.

        Args:
            source: Source file path.
            dest: Destination file path.
            job_type: 'convert' or 'copy'.
            dest_file_exists: Whether the destination file currently exists on disk.
            dest_file_size: Optional current size in bytes of the destination file.
                If provided and the stored size differs, the file is NOT skipped
                (forced reconversion).

        Returns:
            True if the job should be skipped, False otherwise.
        """
        if not dest_file_exists:
            return False
        with self._lock:
            cursor = self._conn.execute(
                "SELECT status, file_size FROM history "
                "WHERE source_path = ? AND dest_path = ? AND job_type = ?",
                (source, dest, job_type),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            if row[0] != "SUCCESS":
                return False
            stored_size = row[1]
            if dest_file_size is not None and stored_size is not None and dest_file_size != stored_size:
                return False
            return True

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()


def datetime_now_utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
