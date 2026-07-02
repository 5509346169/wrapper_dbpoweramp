"""history/write_queue.py: Async writer thread for conversion history.

Workers push log entries onto a queue; a single background thread drains the
queue and writes to SQLite sequentially, eliminating all concurrent write
contention.
"""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from queue import Empty, Queue as StdQueue
from typing import Optional

from src.history.schema import (
    ADD_FILE_SIZE_COLUMN_SQL,
    ADD_TEMP_FILENAME_COLUMN_SQL,
    CREATE_HISTORY_TABLE_SQL,
    INSERT_OR_REPLACE_HISTORY_SQL,
    apply_history_pragmas,
)


def _make_write_queue(worker_model: str) -> tuple[StdQueue, bool]:
    """Build a picklable queue for conversion log entries.

    For 'process' workers (Windows spawn / forking), threading Queue objects
    cannot be pickled because they contain _thread.lock.  We fall back to
    multiprocessing.Manager().Queue() which provides a proxy that is safe to
    send across process boundaries.

    Args:
        worker_model: 'thread' or 'process'.

    Returns:
        A (queue, is_manager_queue) tuple.  is_manager_queue is True when
        the queue is a Manager proxy (caller must manage its lifecycle).
    """
    if worker_model == "process":
        from multiprocessing import get_context

        manager = get_context().Manager()
        return manager.Queue(), True
    return StdQueue(), False


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
    file_size: Optional[int] = None
    temp_filename: Optional[str] = None


class DBWriteQueue:
    """Thread-safe async writer for conversion history.

    Workers push log entries onto a queue. A single background thread
    drains the queue and writes to SQLite sequentially, eliminating
    all concurrent write contention.
    """

    def __init__(self, db_path: Path, worker_model: str = "thread") -> None:
        """Initialize the writer thread.

        Args:
            db_path: Path to the SQLite database file.
            worker_model: 'thread' (uses threading Queue) or 'process'
                (uses multiprocessing.Manager Queue so the object is
                safe to pass through ProcessPoolExecutor.submit).
        """
        self._db_path = db_path
        queue, _is_manager_queue = _make_write_queue(worker_model)
        self._queue: StdQueue = queue
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
        file_size: Optional[int] = None,
        temp_filename: Optional[str] = None,
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
            file_size: Optional file size in bytes of the output file.
            temp_filename: Optional temp staging filename for failed jobs.
        """
        entry = _ConversionLogEntry(
            source=source,
            dest=dest,
            job_type=job_type,
            command=command,
            status=status,
            error_msg=error_msg,
            stdout=stdout,
            file_size=file_size,
            temp_filename=temp_filename,
        )
        self._queue.put((_LogEntryKind.CONVERSION, entry))

    def _writer_loop(self) -> None:
        """Background thread that drains the queue and writes to SQLite."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        apply_history_pragmas(conn)
        conn.execute(CREATE_HISTORY_TABLE_SQL)
        conn.commit()
        try:
            conn.execute(ADD_FILE_SIZE_COLUMN_SQL)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute(ADD_TEMP_FILENAME_COLUMN_SQL)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

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
                    INSERT_OR_REPLACE_HISTORY_SQL,
                    (
                        entry.source,
                        entry.dest,
                        entry.job_type,
                        entry.command,
                        entry.status,
                        entry.error_msg,
                        entry.stdout,
                        timestamp,
                        entry.file_size,
                        None,  # verify_status
                        None,  # verify_reason
                        None,  # verify_format
                        None,  # verify_duration_s
                        entry.temp_filename,
                    ),
                )
                conn.commit()

        conn.close()

    def flush(self) -> None:
        """Signal the writer to shut down and wait for it to finish."""
        self._stop_event.set()
        self._queue.put((_LogEntryKind.SHUTDOWN, None))
        self._thread.join(timeout=5.0)
