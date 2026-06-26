"""index/scan_cache.py: Transient per-run cache of the directory scan result.

The scanner walks the input tree and writes the discovered audio files
(``path, size, mtime, sidecar_files``) to a small SQLite database in
``./tmp/``. The probe phase reads back from this cache instead of
re-walking the directory, eliminating the I/O cost of a second full
filesystem traversal.

The cache is **separate from** ``tmp/index.db`` (the live, post-probe
index used by the conversion pipeline):

* ``tmp/scan_cache_<hash>.db``  — written by scan, read by probe.
  Lives until manually cleaned. Stamped with the run timestamp so the
  filename is unique per run (matches the user-facing spec) and embeds
  an ``input_signature`` row so the probe phase can verify the cache
  matches the current CLI args before trusting it.

* ``tmp/index.db``              — written incrementally as probe results
  arrive; read by the conversion phase; deleted on success.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


# Filename prefix for scan-cache files in ./tmp/. Probe matches ``scan_cache_*.db``.
SCAN_CACHE_PREFIX = "scan_cache_"
SCAN_CACHE_SUFFIX = ".db"

# Schema for the cache_meta table — one row per cache file.
CREATE_CACHE_META_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS cache_meta ("
    "    input_signature TEXT NOT NULL,"
    "    created_at TEXT NOT NULL,"
    "    input_path TEXT NOT NULL,"
    "    excludes TEXT NOT NULL"
    ")"
)

# Schema for the scanned_files table — one row per discovered audio file.
# PRIMARY KEY on source_path ensures the cache survives a partial probe
# (re-running probe overwrites rows idempotently).
CREATE_SCANNED_FILES_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS scanned_files ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    source_path TEXT NOT NULL UNIQUE,"
    "    file_size INTEGER NOT NULL,"
    "    mtime REAL NOT NULL,"
    "    sidecar_files TEXT NOT NULL DEFAULT ''"
    ")"
)

# Insert one row into scanned_files. INSERT OR REPLACE so a re-run of
# scan over the same cache file (e.g. when the cache is reused across
# runs and we want to refresh it) doesn't violate the UNIQUE constraint.
INSERT_SCANNED_FILE_SQL = (
    "INSERT OR REPLACE INTO scanned_files "
    "(source_path, file_size, mtime, sidecar_files) "
    "VALUES (?, ?, ?, ?)"
)


def _compute_signature(input_path: Path, excludes: list[str]) -> str:
    """Return a stable signature for the (input, excludes) tuple.

    Uses the absolute, normalised path of ``input_path`` plus a sorted,
    comma-joined ``excludes`` list so the signature is independent of
    include-order and relative-vs-absolute cwd.
    """
    abs_input = str(input_path.resolve())
    sorted_excludes = ",".join(sorted(excludes))
    raw = f"{abs_input}|{sorted_excludes}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cache_filename_for_run(
    input_path: Path, excludes: list[str], now: datetime | None = None
) -> str:
    """Return the scan-cache filename for a given run.

    The filename embeds an md5 of the run timestamp (matching the
    user-facing spec "md5sum of date and time the script was run")
    plus a short suffix of the input signature so probe can match the
    file without reading the meta row first.

    Args:
        input_path: The input directory/file being scanned.
        excludes: The exclude list (sorted into signature).
        now: Override the timestamp (for tests). Defaults to UTC now.

    Returns:
        A filename like ``scan_cache_a1b2c3d4_e5f6g7h8.db``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%dT%H%M%S")
    ts_hash = hashlib.md5(ts_str.encode("utf-8")).hexdigest()[:12]
    sig = _compute_signature(input_path, excludes)
    return f"{SCAN_CACHE_PREFIX}{ts_hash}_{sig}{SCAN_CACHE_SUFFIX}"


class ScanCache:
    """Writer/reader for the per-run scan-cache SQLite database.

    Lifecycle:

    1. ``ScanCache.create(tmp_dir, input_path, excludes)`` creates the
       cache file in ``tmp_dir`` and returns a writer.
    2. The writer exposes ``add(path, size, mtime, sidecar_files)``
       and ``commit()`` to flush rows.
    3. ``ScanCache.open_latest(tmp_dir, input_path, excludes)`` opens
       the most recent cache file whose ``cache_meta.input_signature``
       matches the current CLI args; returns ``None`` if no valid cache
       is found.

    Thread safety: a single ``RLock`` guards all read/write operations.
    """

    def __init__(self, db_path: Path, conn: sqlite3.Connection) -> None:
        self.db_path = db_path
        self._conn = conn
        self._lock = threading.RLock()

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
    ) -> "ScanCache":
        """Create a fresh scan-cache DB and stamp its meta row.

        Writes to ``<tmp>/scan_cache_<ts_hash>_<sig>.db``. Uses a
        ``.tmp`` filename during construction and atomically renames on
        commit so probe never reads a partial file.
        """
        tmp_dir.mkdir(parents=True, exist_ok=True)
        filename = cache_filename_for_run(input_path, excludes, now=now)
        final_path = tmp_dir / filename
        # Write to a temp filename first so a crash mid-write doesn't
        # produce a cache that probe might later pick up.
        staging_path = tmp_dir / (filename + ".staging")

        conn = sqlite3.connect(str(staging_path), check_same_thread=False)
        try:
            conn.execute(CREATE_CACHE_META_TABLE_SQL)
            conn.execute(CREATE_SCANNED_FILES_TABLE_SQL)
            conn.execute(
                "INSERT INTO cache_meta (input_signature, created_at, input_path, excludes) "
                "VALUES (?, ?, ?, ?)",
                (
                    _compute_signature(input_path, excludes),
                    (now or datetime.now(timezone.utc)).isoformat(),
                    str(input_path.resolve()),
                    ",".join(sorted(excludes)),
                ),
            )
            conn.commit()
        except Exception:
            conn.close()
            try:
                staging_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        # Close the staging connection BEFORE renaming. On Windows an
        # open SQLite handle holds an exclusive lock on the file, and
        # os.replace raises PermissionError if the source is still
        # open. SQLite's WAL mode also leaves a -wal and -shm file
        # alongside the DB that need to move atomically with it.
        conn.close()

        # Atomic rename so probe never observes a partial DB. os.replace
        # moves both the main DB and the WAL/SHM companions.
        os.replace(staging_path, final_path)
        # Re-open against the canonical path so subsequent add() calls
        # write to the live filename.
        conn = sqlite3.connect(str(final_path), check_same_thread=False)
        return cls(final_path, conn)

    @classmethod
    def open_latest(
        cls,
        tmp_dir: Path,
        input_path: Path,
        excludes: list[str],
    ) -> "ScanCache | None":
        """Open the most recent valid scan-cache for the given args.

        Returns ``None`` if no cache files exist or none match the
        current (input_path, excludes) signature.
        """
        if not tmp_dir.exists():
            return None

        current_sig = _compute_signature(input_path, excludes)
        candidates = sorted(
            tmp_dir.glob(f"{SCAN_CACHE_PREFIX}*{SCAN_CACHE_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            # Skip in-progress staging files.
            if candidate.name.endswith(".staging"):
                continue
            try:
                conn = sqlite3.connect(str(candidate), check_same_thread=False)
                row = conn.execute(
                    "SELECT input_signature FROM cache_meta LIMIT 1"
                ).fetchone()
            except (sqlite3.DatabaseError, OSError):
                # Corrupt or unreadable cache; try the next candidate.
                continue
            if row is None or row[0] != current_sig:
                conn.close()
                continue
            return cls(candidate, conn)
        return None

    # ------------------------------------------------------------------
    # Writer API
    # ------------------------------------------------------------------

    def add(
        self,
        source_path: str,
        file_size: int,
        mtime: float,
        sidecar_files: str = "",
    ) -> None:
        """Append one scanned file row (auto-committed)."""
        with self._lock:
            self._conn.execute(
                INSERT_SCANNED_FILE_SQL,
                (source_path, file_size, mtime, sidecar_files),
            )

    def commit(self) -> None:
        """Flush the write transaction."""
        with self._lock:
            self._conn.commit()

    # ------------------------------------------------------------------
    # Reader API
    # ------------------------------------------------------------------

    def iter_files(self):
        """Yield ``(source_path, file_size, mtime, sidecar_files)`` rows.

        Rows are returned in insertion order, which matches the
        sorted-by-path order produced by the scanner.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT source_path, file_size, mtime, sidecar_files "
                "FROM scanned_files ORDER BY id"
            )
            rows = cur.fetchall()
        for row in rows:
            yield row

    def count(self) -> int:
        """Return the number of cached file rows."""
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM scanned_files")
            return int(cur.fetchone()[0])

    def meta(self) -> dict[str, str]:
        """Return the cache_meta row as a dict (empty if missing)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT input_signature, created_at, input_path, excludes "
                "FROM cache_meta LIMIT 1"
            )
            row = cur.fetchone()
        if row is None:
            return {}
        return {
            "input_signature": row[0],
            "created_at": row[1],
            "input_path": row[2],
            "excludes": row[3],
        }

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "ScanCache":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()