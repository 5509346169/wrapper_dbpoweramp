"""history/migrations.py: Schema versioning and migration orchestration.

Provides:
- ``SCHEMA_VERSION``: current schema version constant.
- ``get_schema_version(conn)``: read the highest applied migration version from the DB.
- ``migrate_to_current(db_path)``: bring a DB up to ``SCHEMA_VERSION`` in one
  transactional pass with ``.bak`` backup and ``migration_audit`` rows.
- ``DbVersionInfo`` / ``get_db_version(db_path)``: read-only inspection API.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── version constants ──────────────────────────────────────────────────────────

SCHEMA_VERSION: int = 2

# Each entry: (from_version, to_version, migration_sql, row_backfill_sql)
# The migration_sql is run inside a single transaction; row_backfill_sql is
# run after if non-empty (also inside the same transaction).
MIGRATIONS: list[tuple[int, int, str, str]] = [
    (
        1,
        2,
        (
            "verify_status TEXT"
            ";verify_reason TEXT"
            ";verify_format TEXT"
            ";verify_duration_s REAL"
        ),
        "",  # no row backfill needed — new columns are nullable
    ),
]

# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_add_column(conn: sqlite3.Connection, column_def: str) -> bool:
    """Execute an ``ALTER TABLE history ADD COLUMN`` statement idempotently.

    Returns True if the column was added, False if it already existed
    or the table doesn't exist yet (in which case CREATE_HISTORY_TABLE_SQL
    will create the table with all columns including this one).
    Raises on unexpected errors.
    """
    sql = f"ALTER TABLE history ADD COLUMN {column_def}"
    try:
        conn.execute(sql)
        return True
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "duplicate column name" in msg or "no such table" in msg:
            return False  # table doesn't exist yet OR column already present
        raise  # re-raise unexpected errors


_CREATE_SCHEMA_VERSION_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
)

_CREATE_MIGRATION_AUDIT_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS migration_audit ("
    "    version     INTEGER PRIMARY KEY,"
    "    applied_at  TEXT NOT NULL,"
    "    sql         TEXT NOT NULL,"
    "    row_count   INTEGER"
    ")"
)

_CREATE_SCHEMA_VERSION_ROW_SQL = (
    "INSERT OR IGNORE INTO schema_version (version) VALUES (?)"
)


@dataclass(frozen=True)
class DbVersionInfo:
    """Read-only snapshot of a database's migration state."""

    db_path: Path
    current_version: int  # what the DB on disk says (1 if no schema_version row)
    target_version: int = SCHEMA_VERSION
    backup_paths: list[Path] = field(default_factory=list)
    applied_migrations: list[dict] = field(default_factory=list)

    @property
    def up_to_date(self) -> bool:
        return self.current_version == self.target_version

    @property
    def needs_backup(self) -> bool:
        return self.target_version > self.current_version

    def __str__(self) -> str:
        lines = [
            f"History DB:    {self.db_path}",
            f"Schema:        v{self.current_version}"
            + (" (up-to-date)" if self.up_to_date else f" (need migration: v{self.current_version} -> v{self.target_version})"),
            f"Target:        v{self.target_version}",
        ]
        if self.applied_migrations:
            latest = self.applied_migrations[0]
            lines.append(f"Last migrated: {latest.get('applied_at', 'unknown')}"
                         + (f" (audit row #v{latest.get('version', '?')})"))
        else:
            lines.append("Last migrated: (none)")
        if self.backup_paths:
            lines.append(f"Backups:       {len(self.backup_paths)} file(s) on disk")
            for bp in self.backup_paths:
                size_mb = bp.stat().st_size / (1 << 20)
                lines.append(f"  {bp.name} ({size_mb:.1f} MiB)")
        else:
            lines.append("Backups:       (none)")
        return "\n".join(lines)


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest migration version recorded in the DB.

    A DB with no schema_version row is treated as version 1 (the original
    pre-verify schema).
    """
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        version = row[0] if row and row[0] is not None else 1
        return int(version)
    except sqlite3.OperationalError:
        return 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_version(db_path: Path) -> DbVersionInfo:
    """Read-only inspection of a DB's migration state.

    Never migrates, never writes. Uses a read-only connection.

    Args:
        db_path: Path to the history SQLite database.

    Returns:
        A ``DbVersionInfo`` snapshot.
    """
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except Exception:
        # DB doesn't exist yet — treat as current version (nothing to migrate)
        return DbVersionInfo(
            db_path=db_path,
            current_version=SCHEMA_VERSION,
            target_version=SCHEMA_VERSION,
            backup_paths=[],
            applied_migrations=[],
        )

    try:
        current_version = get_schema_version(conn)

        # Read migration_audit rows (newest first)
        applied_migrations: list[dict] = []
        try:
            rows = conn.execute(
                "SELECT version, applied_at, sql, row_count "
                "FROM migration_audit ORDER BY version DESC"
            ).fetchall()
            applied_migrations = [
                {"version": r[0], "applied_at": r[1], "sql": r[2], "row_count": r[3]}
                for r in rows
            ]
        except sqlite3.OperationalError:
            pass  # migration_audit table doesn't exist yet

        # Find backup files
        backup_paths: list[Path] = []
        if db_path.exists():
            parent = db_path.parent
            stem = db_path.name
            for p in parent.iterdir():
                if p.is_file() and p.name.startswith(stem + ".bak"):
                    backup_paths.append(p)

        return DbVersionInfo(
            db_path=db_path,
            current_version=current_version,
            target_version=SCHEMA_VERSION,
            backup_paths=sorted(backup_paths),
            applied_migrations=applied_migrations,
        )
    finally:
        conn.close()


@dataclass(frozen=True)
class MigrationResult:
    """Outcome of ``migrate_to_current()``."""

    version: int
    rows_migrated: int
    backup_path: Path | None
    messages: list[str] = field(default_factory=list)


def migrate_to_current(db_path: Path) -> MigrationResult:
    """Bring db_path up to SCHEMA_VERSION in one transactional pass.

    Behaviour:
      1. Copy db_path -> db_path + '.bak-<UTCISO>' BEFORE the first schema-
         changing migration. Skip the copy on subsequent runs at the current version.
      2. Run each pending migration inside a single transaction; on any error,
         roll back and restore from the backup.
      3. After schema changes succeed, write a row to ``migration_audit``.
      4. Update the ``schema_version`` row.
      5. Return ``MigrationResult``.

    Args:
        db_path: Path to the history SQLite database.

    Returns:
        A ``MigrationResult`` with version, rows_migrated, and backup_path.
    """
    messages: list[str] = []
    rows_migrated = 0

    # Ensure the DB directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Open (or create) the connection
    conn = sqlite3.connect(str(db_path))

    try:
        # Ensure schema_version table exists
        conn.execute(_CREATE_SCHEMA_VERSION_TABLE_SQL)
        conn.commit()

        current_version = get_schema_version(conn)

        if current_version >= SCHEMA_VERSION:
            messages.append(f"Schema already up-to-date (v{current_version})")
            return MigrationResult(
                version=current_version,
                rows_migrated=0,
                backup_path=None,
                messages=messages,
            )

        # ── backup before first schema change ────────────────────────────────
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        backup_path = db_path.parent / f"{db_path.name}.bak-{ts}"
        # Checkpoint WAL so the .bak is self-contained
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        shutil.copy2(db_path, backup_path)
        messages.append(f"Backup created: {backup_path}")

        # ── apply pending migrations ─────────────────────────────────────────
        for from_ver, to_ver, migration_sql, backfill_sql in MIGRATIONS:
            if from_ver >= current_version:
                applied_at = _utc_now_iso()
                # Run inside a transaction
                try:
                    # Count rows (table may not exist yet)
                    try:
                        cursor = conn.execute("SELECT COUNT(*) FROM history")
                        total_rows = cursor.fetchone()[0]
                    except sqlite3.OperationalError:
                        total_rows = 0

                    conn.execute("BEGIN")
                    try:
                        # Apply the migration SQL using safe, idempotent column additions
                        for stmt in migration_sql.split(";"):
                            stmt = stmt.strip()
                            if stmt:
                                if stmt.startswith("PRAGMA"):
                                    conn.execute(stmt)
                                else:
                                    # Handle "column_name TYPE" syntax from MIGRATIONS
                                    _safe_add_column(conn, stmt)

                        # Row backfill (if any)
                        if backfill_sql.strip():
                            conn.execute(backfill_sql)

                        # Write migration_audit row
                        conn.execute(_CREATE_MIGRATION_AUDIT_TABLE_SQL)
                        conn.execute(
                            "INSERT INTO migration_audit (version, applied_at, sql, row_count) VALUES (?, ?, ?, ?)",
                            (to_ver, applied_at, migration_sql, total_rows),
                        )

                        # Update schema_version
                        conn.execute(
                            "DELETE FROM schema_version WHERE version = ?",
                            (to_ver,),
                        )
                        conn.execute(
                            "INSERT INTO schema_version (version) VALUES (?)",
                            (to_ver,),
                        )

                        conn.commit()
                        rows_migrated += total_rows
                        messages.append(
                            f"Migration v{from_ver} -> v{to_ver}: "
                            f"{total_rows} row(s) audited, backup at {backup_path.name}"
                        )
                    except Exception:
                        conn.rollback()
                        # Restore from backup
                        if backup_path.exists():
                            shutil.copy2(backup_path, db_path)
                        raise
                except Exception as exc:
                    messages.append(f"Migration failed: {exc}")
                    raise

        return MigrationResult(
            version=SCHEMA_VERSION,
            rows_migrated=rows_migrated,
            backup_path=backup_path,
            messages=messages,
        )

    finally:
        conn.close()
