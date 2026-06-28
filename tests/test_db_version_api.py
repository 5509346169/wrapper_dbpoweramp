"""tests/test_db_version_api.py: Tests for get_db_version() read-only API."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _create_v1_db(path: Path) -> None:
    """Create a v1 schema DB (without verify columns or schema_version table).

    Creates a table matching the original pre-verify app schema (with id,
    error_msg, stdout, file_size but no verify columns) so migrate_to_current()
    has real work to do.
    """
    conn = sqlite3.connect(str(path))
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
        ("/src.flac", "/dst.flac", "convert", "ffmpeg", "SUCCESS", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def _create_v2_db(path: Path) -> None:
    """Create a v2 schema DB with schema_version already set."""
    _create_v1_db(path)
    from src.history.migrations import migrate_to_current
    migrate_to_current(path)


class TestGetDbVersion:
    """Tests for get_db_version() read-only API."""

    def test_readonly_connection(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v2_db(db_path)

        info = get_db_version(db_path)
        assert info.current_version == 2
        assert info.up_to_date is True

    def test_v1_db_needs_migration(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)

        info = get_db_version(db_path)
        assert info.current_version == 1
        assert info.up_to_date is False
        assert info.needs_backup is True

    def test_str_contains_schema_v2(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v2_db(db_path)

        info = get_db_version(db_path)
        s = str(info)
        assert "Schema:        v2" in s

    def test_str_contains_up_to_date(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v2_db(db_path)

        info = get_db_version(db_path)
        s = str(info)
        assert "(up-to-date)" in s

    def test_applied_migrations_populated(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v2_db(db_path)

        info = get_db_version(db_path)
        assert len(info.applied_migrations) >= 1
        assert info.applied_migrations[0]["version"] == 2

    def test_backup_paths_populated(self, tmp_path: Path):
        from src.history.migrations import get_db_version

        db_path = tmp_path / "history.db"
        _create_v2_db(db_path)

        info = get_db_version(db_path)
        assert len(info.backup_paths) == 1
        assert info.backup_paths[0].name.startswith(db_path.name + ".bak")

    def test_new_db_returns_current_version(self, tmp_path: Path):
        from src.history.migrations import SCHEMA_VERSION, get_db_version

        db_path = tmp_path / "nonexistent.db"
        info = get_db_version(db_path)
        assert info.current_version == SCHEMA_VERSION
        assert info.up_to_date is True
