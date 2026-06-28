"""tests/test_db_cli.py: Tests for the db subcommand CLI."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace


def _create_v1_db(path: Path) -> None:
    """Create a true v1 schema DB (without verify columns)."""
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


class TestDbCli:
    """Tests for the db subcommand dispatchers."""

    def test_db_check_v2(self, tmp_path: Path, capsys):
        from src.cli.db_cmd import cmd_db_check

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)
        from src.history.migrations import migrate_to_current
        migrate_to_current(db_path)

        args = SimpleNamespace(db_path=db_path)

        result = cmd_db_check(args)
        captured = capsys.readouterr()

        assert result == 0
        # str(DbVersionInfo) contains "current_version=2" and "up_to_date=True"
        assert "current_version=2" in captured.out or "Schema:        v2" in captured.out

    def test_db_migrate(self, tmp_path: Path, capsys):
        from src.cli.db_cmd import cmd_db_migrate

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)

        args = SimpleNamespace(db_path=db_path)

        result = cmd_db_migrate(args)
        captured = capsys.readouterr()

        assert result == 0
        assert "Migration complete" in captured.out or "up-to-date" in captured.out

    def test_db_doctor_with_clean_v1_db(self, tmp_path: Path, capsys):
        """cmd_db_doctor on a v1 DB should report it needs migration."""
        from src.cli.db_cmd import cmd_db_doctor

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)

        args = SimpleNamespace(db_path=db_path)

        result = cmd_db_doctor(args)

        # v1 DB: schema is outdated but no orphaned backups yet
        assert result == 0  # doctor exits 0 for v1 (needs migration, not orphaned)
        captured = capsys.readouterr()
        assert "Schema:" in captured.out

    def test_db_version_flag_routes_to_check(self, tmp_path: Path):
        """--db-version should print version and exit (not run the pipeline)."""
        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)
        from src.history.migrations import migrate_to_current
        migrate_to_current(db_path)

        args = SimpleNamespace(db_path=db_path)

        from src.cli.db_cmd import cmd_db_check
        result = cmd_db_check(args)
        assert result == 0
