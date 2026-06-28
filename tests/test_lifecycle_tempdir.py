"""tests/test_lifecycle_tempdir.py: Tests for tempdir cleanup lifecycle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _make_closed_temp_file() -> Path:
    """Create a temp file and close its handle immediately, leaving the file on disk."""
    fd, name = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(name)


class TestCleanupIndex:
    """Tests for cleanup_index() lifecycle."""

    def test_cleanup_keeps_on_failure(self):
        from src.app.lifecycle.tempdir import cleanup_index

        db_path = _make_closed_temp_file()

        try:
            cleanup_index(db_path=db_path, failed_count=1, exception_info=None, interrupted=False)
            assert db_path.exists()  # Should be kept
        finally:
            db_path.unlink(missing_ok=True)

    def test_cleanup_keeps_on_exception(self):
        from src.app.lifecycle.tempdir import cleanup_index

        db_path = _make_closed_temp_file()

        try:
            cleanup_index(db_path=db_path, failed_count=0, exception_info="error!", interrupted=False)
            assert db_path.exists()  # Should be kept
        finally:
            db_path.unlink(missing_ok=True)

    def test_cleanup_keeps_on_interrupt(self):
        from src.app.lifecycle.tempdir import cleanup_index

        db_path = _make_closed_temp_file()

        try:
            cleanup_index(db_path=db_path, failed_count=0, exception_info=None, interrupted=True)
            assert db_path.exists()  # Should be kept
        finally:
            db_path.unlink(missing_ok=True)

    def test_cleanup_deletes_on_success(self):
        from src.app.lifecycle.tempdir import cleanup_index

        db_path = _make_closed_temp_file()

        cleanup_index(db_path=db_path, failed_count=0, exception_info=None, interrupted=False)
        assert not db_path.exists()  # Should be deleted

    def test_cleanup_nonexistent_path_noops(self):
        from src.app.lifecycle.tempdir import cleanup_index

        # Should not raise
        cleanup_index(db_path=Path("/nonexistent/db.db"), failed_count=0, exception_info=None, interrupted=False)

    def test_cleanup_none_path_noops(self):
        from src.app.lifecycle.tempdir import cleanup_index

        # Should not raise
        cleanup_index(db_path=None, failed_count=0, exception_info=None, interrupted=False)


class TestSetupTempDir:
    """Tests for setup_temp_dir()."""

    def test_setup_creates_tmp_dir(self, tmp_path: Path, monkeypatch):
        # Change to tmp_path so we don't pollute the workspace
        monkeypatch.chdir(tmp_path)

        from src.app.lifecycle.tempdir import setup_temp_dir

        tmp_dir, index_db = setup_temp_dir()

        assert tmp_dir == Path("tmp")
        assert tmp_dir.exists()
        assert index_db == tmp_dir / "index.db"
