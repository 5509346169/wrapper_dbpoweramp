"""tests/test_purge_failed_audio.py: Tests for purge_failed_audio.py extensions.

The script now:

  - recognises ``status = 'FAILED'`` (wrapper's canonical failure signal),
  - recognises ``verify_status = 'NOT_OK'`` (post-write verifier's status),
  - supports a ``--zero-byte-only`` flag to restrict to rows with
    ``file_size = 0`` or NULL,
  - auto-detects ``audio_verify.db`` next to the history DB when --verify-db
    is omitted.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


def _seed_history(db_path: Path, *rows: dict) -> None:
    """Create a history table and seed the provided rows."""
    with sqlite3.connect(db_path) as conn:
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
            "    file_size INTEGER,"
            "    verify_status TEXT,"
            "    verify_reason TEXT,"
            "    verify_format TEXT,"
            "    verify_duration_s REAL,"
            "    UNIQUE(source_path, dest_path)"
            ")"
        )
        for row in rows:
            conn.execute(
                "INSERT INTO history "
                "(source_path, dest_path, job_type, status, file_size, verify_status, verify_reason, error_msg) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("source_path"),
                    row.get("dest_path"),
                    row.get("job_type", "convert"),
                    row.get("status", "SUCCESS"),
                    row.get("file_size"),
                    row.get("verify_status"),
                    row.get("verify_reason"),
                    row.get("error_msg"),
                ),
            )
        conn.commit()


def _row_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]


class TestPurgeScriptArgv:
    """Drive purge_failed_audio.main() programmatically via argv."""

    def run(self, monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
        monkeypatch.setattr(sys, "argv", ["purge_failed_audio.py", *args])
        # Reload to pick up the new argv.
        if "purge_failed_audio" in sys.modules:
            del sys.modules["purge_failed_audio"]
        import importlib
        mod = importlib.import_module("purge_failed_audio")
        return mod.main()

    def test_failed_status_row_is_picked_up(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """A row logged as FAILED by run_job must surface as a candidate."""
        db = tmp_path / "history.db"
        _seed_history(
            db,
            {
                "source_path": "A:/src.m4a",
                "dest_path": "B:/dst.m4a",
                "status": "FAILED",
                "error_msg": "empty output",
                "file_size": 0,
            },
            # An unrelated SUCCESS row that must survive.
            {
                "source_path": "C:/src.m4a",
                "dest_path": "D:/dst.m4a",
                "status": "SUCCESS",
                "file_size": 1024,
            },
        )

        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, "--history-db", str(db))
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "1 record(s) to delete" in out
        assert "dst.m4a" in out

    def test_zero_byte_only_filter_restricts_candidates(self, tmp_path: Path, monkeypatch, capsys) -> None:
        db = tmp_path / "history.db"
        _seed_history(
            db,
            # Candidate A: failed + zero bytes → still in scope.
            {
                "source_path": "A:/src.m4a",
                "dest_path": "B:/dst.m4a",
                "status": "FAILED",
                "file_size": 0,
                "error_msg": "empty",
            },
            # Candidate B: failed + nonzero file_size → must be excluded.
            {
                "source_path": "C:/src.m4a",
                "dest_path": "D:/dst.m4a",
                "status": "FAILED",
                "file_size": 4096,
                "error_msg": "CoreConverter exit 2",
            },
        )

        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, "--history-db", str(db), "--zero-byte-only")
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "1 record(s) to delete" in out
        # The nonzero byte row should NOT be in the preview table.
        assert "D:/dst.m4a" not in out

    def test_verify_db_auto_detect(self, tmp_path: Path, monkeypatch, capsys) -> None:
        db = tmp_path / "history.db"
        _seed_history(db)
        # audio_verify.db next to the history DB → auto-detect picks it up.
        verify_db = tmp_path / "audio_verify.db"
        with sqlite3.connect(verify_db) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS results "
                "(path TEXT PRIMARY KEY, status TEXT)"
            )
            c.execute(
                "INSERT INTO results VALUES (?, ?)",
                ("Z:/orphan.m4a", "ERROR"),
            )

        with pytest.raises(SystemExit) as exc:
            self.run(monkeypatch, "--history-db", str(db))
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Auto-detected audio_verify.db" in out
        # No DELETE happens in dry-run mode.
        assert _row_count(db) == 0

    def test_execute_deletes_failed_rows(self, tmp_path: Path, monkeypatch, capsys) -> None:
        db = tmp_path / "history.db"
        _seed_history(
            db,
            {
                "source_path": "A:/src.m4a",
                "dest_path": "B:/dst.m4a",
                "status": "FAILED",
                "file_size": 0,
                "error_msg": "empty",
            },
            {
                "source_path": "C:/src.m4a",
                "dest_path": "D:/dst.m4a",
                "status": "SUCCESS",
                "file_size": 4096,
            },
        )

        # --execute --yes deletes and exits cleanly.
        self.run(
            monkeypatch,
            "--history-db", str(db),
            "--execute", "--yes",
        )
        out = capsys.readouterr().out
        assert "Deleted 1 record" in out
        # The SUCCESS row remains untouched.
        assert _row_count(db) == 1
