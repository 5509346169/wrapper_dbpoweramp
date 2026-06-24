"""History database module for tracking conversion and copy jobs."""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Optional


class _LogEntryKind(str, Enum):
    """Types of entries that can be pushed to the write queue."""

    CONVERSION = "conversion"
    SHUTDOWN = "shutdown"


@dataclass
class _ConversionLogEntry:
    """Payload for a conversion log entry pushed onto the queue."""

    source: str
    dest: str
    job_type: str
    command: Optional[str]
    status: str
    error_msg: Optional[str]
    stdout: Optional[str]


class DBWriteQueue:
    """Thread-safe async writer for conversion history.

    Workers push log entries onto a queue. A single background thread
    drains the queue and writes to SQLite sequentially, eliminating
    all concurrent write contention.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the writer thread.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = db_path
        self._queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

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
        """Queue a conversion log entry for async writing.

        This method returns immediately; the actual DB write happens
        in the background writer thread.

        Args:
            source: Source file path.
            dest: Destination file path.
            job_type: 'convert' or 'copy'.
            command: The command string; may be None for job_type='copy'.
            status: JobStatus value (e.g. 'SUCCESS', 'FAILED', 'SKIPPED').
            error_msg: Optional error message for failed jobs.
            stdout: Optional captured stdout for the job.
        """
        entry = _ConversionLogEntry(
            source=source,
            dest=dest,
            job_type=job_type,
            command=command,
            status=status,
            error_msg=error_msg,
            stdout=stdout,
        )
        self._queue.put((_LogEntryKind.CONVERSION, entry))

    def _writer_loop(self) -> None:
        """Background thread that drains the queue and writes to SQLite."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
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
        conn.commit()

        while not self._stop_event.is_set():
            try:
                kind, entry = self._queue.get(timeout=0.1)
            except Empty:
                continue

            if kind == _LogEntryKind.SHUTDOWN:
                break

            if kind == _LogEntryKind.CONVERSION:
                timestamp = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO history "
                    "  (source_path, dest_path, job_type, command, status, error_msg, stdout, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.source,
                        entry.dest,
                        entry.job_type,
                        entry.command,
                        entry.status,
                        entry.error_msg,
                        entry.stdout,
                        timestamp,
                    ),
                )
                conn.commit()

        conn.close()

    def flush(self) -> None:
        """Signal the writer to shut down and wait for it to finish."""
        self._stop_event.set()
        self._queue.put((_LogEntryKind.SHUTDOWN, None))
        self._thread.join(timeout=5.0)


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
        # Enable WAL mode for better concurrent write performance
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Wait up to 5 seconds for locks instead of failing immediately
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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

        NOTE: source-file mtime is NOT checked. A re-encode of an unchanged
        source file will be re-run even if a SUCCESS record already exists.
        This is a known limitation — the index tracks dest_path and job_type
        match but not the source's modification time.

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
        with self._lock:
            cursor = self._conn.execute(
                "SELECT status FROM history "
                "WHERE source_path = ? AND dest_path = ? AND job_type = ?",
                (source, dest, job_type),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            return row[0] == "SUCCESS"

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()
