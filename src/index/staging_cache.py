"""index/staging_cache.py: Per-run md5sum staging association cache.

Stores the ``source_path -> md5sum -> temp_path -> dest_path`` mapping
for each job so subsequent runs can recover the staging association
without re-computing md5sums or re-discovering the dest path.

The cache is a separate SQLite database in ``./tmp/`` keyed by the
same ``input_signature`` as the scan-cache, but named
``staging_cache_<ts_hash>_<sig>.db`` so it is independent of the
scan-cache lifecycle.

Schema
------
``staged_jobs`` — one row per source file::

    CREATE TABLE IF NOT EXISTS staged_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        input_signature TEXT NOT NULL,
        md5sum TEXT NOT NULL,
        source_path TEXT NOT NULL,
        dest_path TEXT NOT NULL,
        temp_infile TEXT NOT NULL,
        temp_outfile TEXT NOT NULL,
        temp_filename TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        last_seen_at TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        error_msg TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_jobs_lookup
        ON staged_jobs(input_signature, md5sum);

``staged_jobs_debug`` — append-only event log::

    CREATE TABLE IF NOT EXISTS staged_jobs_debug (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        md5sum TEXT NOT NULL,
        ts TEXT NOT NULL,
        event TEXT NOT NULL,
        detail TEXT NOT NULL
    );

Status values: ``PENDING``, ``SUCCESS``, ``FAILED``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


STAGING_CACHE_PREFIX = "staging_cache_"
STAGING_CACHE_SUFFIX = ".db"

CREATE_STAGED_JOBS_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS staged_jobs ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    input_signature TEXT NOT NULL,"
    "    md5sum TEXT NOT NULL,"
    "    source_path TEXT NOT NULL,"
    "    dest_path TEXT NOT NULL,"
    "    temp_infile TEXT NOT NULL,"
    "    temp_outfile TEXT NOT NULL,"
    "    temp_filename TEXT NOT NULL,"
    "    status TEXT NOT NULL DEFAULT 'PENDING',"
    "    last_seen_at TEXT NOT NULL,"
    "    attempt_count INTEGER NOT NULL DEFAULT 0,"
    "    error_msg TEXT"
    ")"
)

CREATE_STAGED_JOBS_LOOKUP_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_staged_jobs_lookup "
    "ON staged_jobs(input_signature, md5sum)"
)

CREATE_STAGED_JOBS_DEBUG_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS staged_jobs_debug ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    md5sum TEXT NOT NULL,"
    "    ts TEXT NOT NULL,"
    "    event TEXT NOT NULL,"
    "    detail TEXT NOT NULL"
    ")"
)

# Metadata table: stores the run's input_signature so open_latest can verify
# a cache's signature even when staged_jobs is empty.
CREATE_CACHE_META_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS cache_meta ("
    "    id INTEGER PRIMARY KEY,"
    "    input_signature TEXT NOT NULL,"
    "    created_at TEXT NOT NULL"
    ")"
)

# Insert metadata row (id=1 ensures exactly one row).
INSERT_CACHE_META_SQL = (
    "INSERT OR REPLACE INTO cache_meta (id, input_signature, created_at) VALUES (1, ?, ?)"
)

# Select metadata row for signature verification.
GET_CACHE_META_SQL = (
    "SELECT input_signature FROM cache_meta LIMIT 1"
)

UPSERT_STAGED_JOB_SQL = (
    "INSERT OR REPLACE INTO staged_jobs "
    "(input_signature, md5sum, source_path, dest_path, "
    " temp_infile, temp_outfile, temp_filename, status, last_seen_at, attempt_count) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 0)"
)

MARK_STATUS_SQL = (
    "UPDATE staged_jobs "
    "SET status = ?, error_msg = ?, "
    "    attempt_count = attempt_count + 1, "
    "    last_seen_at = ? "
    "WHERE md5sum = ? AND input_signature = ?"
)

LOG_DEBUG_SQL = (
    "INSERT INTO staged_jobs_debug (md5sum, ts, event, detail) VALUES (?, ?, ?, ?)"
)

GET_BY_MD5_SQL = (
    "SELECT md5sum, source_path, dest_path, temp_infile, temp_outfile, "
    "       temp_filename, status, error_msg "
    "FROM staged_jobs "
    "WHERE md5sum = ? AND input_signature = ? "
    "LIMIT 1"
)

# Import the signature computation from scan_cache so we stay in sync.
def _compute_signature(input_path: Path, excludes: list[str]) -> str:
    """Return a stable signature for the (input, excludes) tuple."""
    import hashlib
    abs_input = str(input_path.resolve())
    sorted_excludes = ",".join(sorted(excludes))
    raw = f"{abs_input}|{sorted_excludes}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def staging_cache_filename_for_run(
    input_path: Path, excludes: list[str], now: datetime | None = None
) -> str:
    """Return the staging-cache filename for a given run.

    Mirrors the scan-cache naming convention so both caches can coexist
    in ``./tmp/`` with the same timestamp/signature namespace.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    import hashlib
    ts_str = now.strftime("%Y%m%dT%H%M%S")
    ts_hash = hashlib.md5(ts_str.encode("utf-8")).hexdigest()[:12]
    sig = _compute_signature(input_path, excludes)
    return f"{STAGING_CACHE_PREFIX}{ts_hash}_{sig}{STAGING_CACHE_SUFFIX}"


class StagingCache:
    """Writer/reader for the per-run staging-association SQLite cache.

    Lifecycle:

    1. ``StagingCache.create(tmp_dir, input_path, excludes)`` creates the
       cache file and returns a writer.
    2. The writer exposes ``upsert()``, ``mark_status()``,
       ``log_debug()``, ``get_by_md5()``.
    3. ``StagingCache.open_latest(tmp_dir, input_path, excludes)`` opens
       the most recent cache whose ``input_signature`` matches.

    Thread safety: a single ``RLock`` guards all read/write operations.
    """

    def __init__(self, db_path: Path, conn: sqlite3.Connection) -> None:
        self.db_path = db_path
        self._conn = conn
        self._lock = threading.RLock()
        # Derived once at open time so callers always have the current run's sig.
        self._input_signature = ""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        tmp_dir: Path,
        input_path: Path,
        excludes: list[str],
        now: datetime | None = None,
    ) -> "StagingCache":
        """Create a fresh staging-cache DB.

        Writes to ``<tmp>/staging_cache_<ts_hash>_<sig>.db`` using an
        atomic ``.staging`` rename so probe never reads a partial file.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        filename = staging_cache_filename_for_run(input_path, excludes, now=now)
        final_path = tmp_dir / filename
        staging_path = tmp_dir / (filename + ".staging")
        sig = _compute_signature(input_path, excludes)

        conn = sqlite3.connect(str(staging_path), check_same_thread=False)
        try:
            conn.execute(CREATE_STAGED_JOBS_TABLE_SQL)
            conn.execute(CREATE_STAGED_JOBS_LOOKUP_INDEX_SQL)
            conn.execute(CREATE_STAGED_JOBS_DEBUG_TABLE_SQL)
            conn.execute(CREATE_CACHE_META_TABLE_SQL)
            conn.execute(INSERT_CACHE_META_SQL, (sig, (now or datetime.now(timezone.utc)).isoformat()))
            conn.commit()
        except Exception:
            conn.close()
            try:
                staging_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        conn.close()
        os.replace(staging_path, final_path)
        conn = sqlite3.connect(str(final_path), check_same_thread=False)
        instance = cls(final_path, conn)
        instance._input_signature = sig
        return instance

    @classmethod
    def open_latest(
        cls,
        tmp_dir: Path,
        input_path: Path,
        excludes: list[str],
    ) -> "StagingCache | None":
        """Open the most recent staging-cache matching the current args.

        Returns ``None`` if no matching cache exists.
        """
        if not tmp_dir.exists():
            return None

        current_sig = _compute_signature(input_path, excludes)
        candidates = sorted(
            tmp_dir.glob(f"{STAGING_CACHE_PREFIX}*{STAGING_CACHE_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if candidate.name.endswith(".staging"):
                continue
            try:
                conn = sqlite3.connect(str(candidate), check_same_thread=False)
                row = conn.execute(GET_CACHE_META_SQL).fetchone()
                if row is not None:
                    # Verify the cache's input_signature matches current run.
                    if row[0] != current_sig:
                        conn.close()
                        continue
                    instance = cls(candidate, conn)
                    instance._input_signature = current_sig
                    return instance
                # No cache_meta row — skip this candidate.
                conn.close()
                continue
            except (sqlite3.DatabaseError, OSError):
                if "conn" in dir():
                    conn.close()
                continue
        return None

    # ------------------------------------------------------------------
    # Writer API
    # ------------------------------------------------------------------

    def upsert(
        self,
        source_path: str,
        dest_path: str,
        md5sum: str,
        temp_infile: str,
        temp_outfile: str,
        temp_filename: str,
    ) -> None:
        """Insert or update a staged-job entry."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                UPSERT_STAGED_JOB_SQL,
                (
                    self._input_signature,
                    md5sum,
                    source_path,
                    dest_path,
                    temp_infile,
                    temp_outfile,
                    temp_filename,
                    now,
                ),
            )
            self._conn.commit()

    def mark_status(
        self,
        md5sum: str,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        """Update the status of a staged job.

        Increments ``attempt_count`` and sets ``last_seen_at`` to now.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                MARK_STATUS_SQL,
                (status, error_msg, now, md5sum, self._input_signature),
            )
            self._conn.commit()

    def log_debug(self, md5sum: str, event: str, detail: str) -> None:
        """Append a debug event to the append-only debug log."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                LOG_DEBUG_SQL,
                (md5sum, now, event, detail),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Reader API
    # ------------------------------------------------------------------

    def get_by_md5(self, md5sum: str) -> Optional[dict]:
        """Return the staged-job row for the given md5sum, or None."""
        with self._lock:
            cur = self._conn.execute(
                GET_BY_MD5_SQL,
                (md5sum, self._input_signature),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "md5sum": row[0],
            "source_path": row[1],
            "dest_path": row[2],
            "temp_infile": row[3],
            "temp_outfile": row[4],
            "temp_filename": row[5],
            "status": row[6],
            "error_msg": row[7],
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "StagingCache":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
