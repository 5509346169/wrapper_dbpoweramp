"""History database module for tracking conversion and copy jobs."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ConversionDB:
    """Wraps a SQLite connection for tracking conversion/copy history.

    Supports resume-check semantics: a job is skippable only if a matching
    (source_path, dest_path, job_type) row exists with status=SUCCESS and the
    destination file still exists on disk.
    """

    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the history table exists.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
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
        self._conn.commit()

    def get_record(self, source: str, dest: str) -> Optional[dict]:
        """Return the row matching (source_path, dest_path), or None.

        Args:
            source: Source file path.
            dest: Destination file path.

        Returns:
            Dict with columns: id, source_path, dest_path, job_type, command,
            status, error_msg, stdout, timestamp. Or None if no row exists.
        """
        cursor = self._conn.execute(
            "SELECT id, source_path, dest_path, job_type, command, status, "
            "       error_msg, stdout, timestamp "
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
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO history "
            "  (source_path, dest_path, job_type, command, status, error_msg, stdout, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source, dest, job_type, command, status, error_msg, stdout, timestamp),
        )
        self._conn.commit()

    def should_skip(
        self, source: str, dest: str, job_type: str, dest_file_exists: bool
    ) -> bool:
        """Decide whether to skip a job based on history.

        Returns True iff a row exists with matching (source_path, dest_path,
        job_type), the status is 'SUCCESS', AND dest_file_exists is True.

        A file previously logged as 'copy' but now requested as 'convert' will
        NOT be skipped — job_type must also match.

        Args:
            source: Source file path.
            dest: Destination file path.
            job_type: 'convert' or 'copy'.
            dest_file_exists: Whether the destination file currently exists on disk.

        Returns:
            True if the job should be skipped, False otherwise.
        """
        if not dest_file_exists:
            return False
        cursor = self._conn.execute(
            "SELECT status FROM history "
            "WHERE source_path = ? AND dest_path = ? AND job_type = ?",
            (source, dest, job_type),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        return row[0] == "SUCCESS"
