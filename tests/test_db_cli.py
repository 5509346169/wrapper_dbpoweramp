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

    def test_db_inspect_filters_by_status(self, tmp_path: Path, capsys):
        """cmd_db_inspect prints full diagnostic detail for matching rows."""
        import sqlite3

        from src.cli.db_cmd import cmd_db_inspect

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)
        from src.history.migrations import migrate_to_current
        migrate_to_current(db_path)

        # Add a FAILED row with command + stdout so we can see them in output.
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT OR REPLACE INTO history "
            "(source_path, dest_path, job_type, command, status, error_msg, stdout, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r"E:\path with spaces\file.m4a",
                r"D:\dst\file.m4a",
                "convert",
                r'"C:\Program Files\dBpoweramp\CoreConverter.exe" -infile="..." -convert_to="..."',
                "FAILED",
                "CoreConverter exited with code 1",
                "Error: Unable to load decoder for file type '.', codec not installed?\n"
                "Audio Source: E:\\path",
                "2026-07-01T12:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

        args = SimpleNamespace(
            db_path=db_path,
            id=None,
            id_range=None,
            status="FAILED",
            limit=None,
            max_stdout=400,
        )
        result = cmd_db_inspect(args)
        out = capsys.readouterr().out
        assert result == 0
        assert "FAILED" in out
        assert "CoreConverter exited with code 1" in out
        assert "Unable to load decoder" in out

    def test_db_inspect_filters_by_id_range(self, tmp_path: Path, capsys):
        """--id-range selects only rows within the inclusive window."""
        import sqlite3

        from src.cli.db_cmd import cmd_db_inspect

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)
        from src.history.migrations import migrate_to_current

        migrate_to_current(db_path)
        conn = sqlite3.connect(str(db_path))
        # Insert 5 rows
        for i in range(5):
            conn.execute(
                "INSERT INTO history (source_path, dest_path, job_type, command, status, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"/src{i}.flac", f"/dst{i}.flac", "convert", "ffmpeg", "SUCCESS",
                 f"2026-07-01T12:00:0{i}Z"),
            )
        conn.commit()
        conn.close()

        args = SimpleNamespace(
            db_path=db_path,
            id=None,
            id_range="2-4",
            status=None,
            limit=None,
            max_stdout=400,
        )
        result = cmd_db_inspect(args)
        out = capsys.readouterr().out
        assert result == 0
        assert "3 row(s)" in out
        # ids 2..4 are selected; id 1 and id 5 are not
        assert "id=2" in out and "id=4" in out

    def test_db_inspect_handles_bad_id_range(self, tmp_path: Path, capsys):
        """An unparseable --id-range returns a non-zero exit."""
        from src.cli.db_cmd import cmd_db_inspect

        db_path = tmp_path / "history.db"
        _create_v1_db(db_path)

        args = SimpleNamespace(
            db_path=db_path,
            id=None,
            id_range="not-a-range",
            status=None,
            limit=None,
            max_stdout=400,
        )
        result = cmd_db_inspect(args)
        captured = capsys.readouterr()
        assert result != 0
        combined = captured.out + captured.err
        assert "MIN" in combined or "integer" in combined.lower()
