"""tests/test_history_migrations.py: Tests for the schema migration orchestrator."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


class TestMigrationOrchestrator:
    """Tests for migrate_to_current() and get_schema_version()."""

    def _create_v1_schema(self, conn: sqlite3.Connection) -> None:
        """Create a true v1 history table matching the pre-verify app schema.

        This creates the table WITHOUT verify columns so that migrate_to_current()
        has real work to do. It includes id/error_msg/stdout/file_size which were
        always part of the original app schema.
        """
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    source_path TEXT NOT NULL,"
            "    dest_path TEXT NOT NULL,"
            "    job_type TEXT NOT NULL,"
            "    command TEXT,"
            "    status TEXT NOT NULL,"
            "    error_msg TEXT,"
            "    stdout TEXT,"
            "    timestamp TEXT,"
            "    file_size INTEGER,"
            "    UNIQUE(source_path, dest_path)"
            ")"
        )
        conn.execute(
            "INSERT INTO history (source_path, dest_path, job_type, command, status, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("/src.flac", "/dst.flac", "convert", "ffmpeg ...", "SUCCESS", "2026-01-01T00:00:00Z"),
        )
        conn.commit()

    def _create_v1_db(self, path: Path) -> None:
        """Create a v1 schema DB (without verify columns or schema_version table)."""
        conn = sqlite3.connect(str(path))
        self._create_v1_schema(conn)
        conn.close()

    def _create_v1_db(self, path: Path) -> None:
        """Create a v1 schema DB (without verify columns or schema_version table)."""
        conn = sqlite3.connect(str(path))
        self._create_v1_schema(conn)
        conn.close()

    def test_get_schema_version_unknown_db(self, tmp_path: Path):
        from src.history.migrations import get_schema_version

        db_path = tmp_path / "new.db"
        conn = sqlite3.connect(str(db_path))
        version = get_schema_version(conn)
        conn.close()
        assert version == 1  # unknown DB → treated as v1

    def test_migrate_v1_to_v2(self, tmp_path: Path):
        from src.history.migrations import SCHEMA_VERSION, get_schema_version, migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        # Verify we're at v1
        conn = sqlite3.connect(str(db_path))
        assert get_schema_version(conn) == 1
        conn.close()

        # Run migration
        result = migrate_to_current(db_path)
        assert result.version == SCHEMA_VERSION
        assert result.rows_migrated >= 1
        assert result.backup_path is not None
        assert result.backup_path.exists()

        # Verify we're now at v2
        conn = sqlite3.connect(str(db_path))
        assert get_schema_version(conn) == SCHEMA_VERSION
        conn.close()

        # Verify the verify columns exist
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("PRAGMA table_info(history)").fetchall()
        col_names = {r[1] for r in rows}
        assert "verify_status" in col_names
        assert "verify_reason" in col_names
        assert "verify_format" in col_names
        assert "verify_duration_s" in col_names
        conn.close()

    def test_migrate_idempotent(self, tmp_path: Path):
        from src.history.migrations import SCHEMA_VERSION, migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        # First migration
        result1 = migrate_to_current(db_path)
        assert result1.rows_migrated >= 1
        backup1 = result1.backup_path

        # Second migration should be a no-op
        result2 = migrate_to_current(db_path)
        assert result2.rows_migrated == 0
        assert "up-to-date" in result2.messages[0]

        # No extra backup should have been created
        assert backup1.exists()

    def test_migration_audit_row(self, tmp_path: Path):
        from src.history.migrations import migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        migrate_to_current(db_path)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT version, sql FROM migration_audit ORDER BY version").fetchall()
        conn.close()

        assert len(rows) >= 1
        assert rows[0][0] == 2  # version 2
        assert "verify_status" in rows[0][1]

    def test_backward_compat_get_record(self, tmp_path: Path):
        from src.history.conversion_db import ConversionDB

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        # Migrate
        from src.history.migrations import migrate_to_current

        migrate_to_current(db_path)

        # Open via ConversionDB and read
        db = ConversionDB(db_path)
        record = db.get_record("/src.flac", "/dst.flac")
        db.close()

        assert record is not None
        # Standard columns still work
        assert record["source_path"] == "/src.flac"
        assert record["status"] == "SUCCESS"
        # New verify columns are present (as None for v1 rows)
        assert "verify_status" in record
        assert "verify_reason" in record
        assert "verify_format" in record
        assert "verify_duration_s" in record

    def test_backward_compat_log_conversion_without_verify_kwargs(self, tmp_path: Path):
        from src.history.conversion_db import ConversionDB
        from src.history.migrations import migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)
        migrate_to_current(db_path)

        db = ConversionDB(db_path)
        db.log_conversion(
            source="/src2.flac",
            dest="/dst2.flac",
            job_type="convert",
            command="ffmpeg",
            status="SUCCESS",
        )
        db.close()

        # Read it back
        db2 = ConversionDB(db_path)
        record = db2.get_record("/src2.flac", "/dst2.flac")
        db2.close()

        assert record is not None
        assert record["status"] == "SUCCESS"
        # New columns are NULL
        assert record["verify_status"] is None
        assert record["verify_reason"] is None

    def test_log_conversion_with_verify_kwargs(self, tmp_path: Path):
        from src.history.conversion_db import ConversionDB
        from src.history.migrations import migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)
        migrate_to_current(db_path)

        db = ConversionDB(db_path)
        db.log_conversion(
            source="/src3.flac",
            dest="/dst3.flac",
            job_type="convert",
            command="ffmpeg",
            status="SUCCESS",
            file_size=1234567,
            verify_status="OK",
            verify_reason=None,
            verify_format="FLAC/PCM_16",
            verify_duration_s=180.5,
        )
        db.close()

        db2 = ConversionDB(db_path)
        record = db2.get_record("/src3.flac", "/dst3.flac")
        db2.close()

        assert record["verify_status"] == "OK"
        assert record["verify_reason"] is None
        assert record["verify_format"] == "FLAC/PCM_16"
        assert record["verify_duration_s"] == 180.5

    def test_migration_creates_backup(self, tmp_path: Path):
        from src.history.migrations import migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        result = migrate_to_current(db_path)

        assert result.backup_path is not None
        assert result.backup_path.exists()
        assert result.backup_path.name.startswith(db_path.name + ".bak")
        # The backup should be readable
        conn = sqlite3.connect(str(result.backup_path))
        count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        conn.close()
        assert count >= 1

    def test_get_db_version_readonly(self, tmp_path: Path):
        from src.history.migrations import get_db_version, migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)
        migrate_to_current(db_path)

        info = get_db_version(db_path)

        assert info.db_path == db_path
        assert info.current_version == 2
        assert info.target_version == 2
        assert info.up_to_date is True
        assert len(info.applied_migrations) >= 1
        assert len(info.backup_paths) == 1  # the migration backup

    def test_get_db_version_v1(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)

        info = get_db_version(db_path)
        assert info.current_version == 1
        assert info.up_to_date is False
        assert info.needs_backup is True

    def test_get_db_version_str_output(self, tmp_path: Path):
        from src.history.migrations import get_db_version, migrate_to_current

        db_path = tmp_path / "history.db"
        self._create_v1_db(db_path)
        migrate_to_current(db_path)

        info = get_db_version(db_path)
        s = str(info)
        assert "Schema:        v2" in s
        assert "(up-to-date)" in s
