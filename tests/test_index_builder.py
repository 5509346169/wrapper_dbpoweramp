"""tests/test_index_builder.py: Tests for IndexBuilder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.index.builder import IndexBuilder
from src.index.scanner import IndexRow


class TestIndexBuilderTableCreation:
    """Tests for IndexBuilder table creation and is_lossy migration."""

    def test_create_table_includes_is_lossy_column(self, tmp_path: Path) -> None:
        """A fresh table is created with the is_lossy column."""
        db_path = tmp_path / "test_index.db"
        with IndexBuilder(db_path) as builder:
            cur = builder._conn.execute("PRAGMA table_info(index_entries)")
            cols = {row[1] for row in cur.fetchall()}
        assert "is_lossy" in cols

    def test_add_inserts_row(self, tmp_path: Path) -> None:
        """add() inserts a row that can be retrieved via iter_rows."""
        db_path = tmp_path / "test_index.db"
        row = IndexRow(
            source_path="D:/music/file.mp3",
            dest_path="D:/output/file.flac",
            job_type="convert",
            file_size=1234,
            sidecar_files="",
            mtime=1000.0,
            is_lossy=True,
        )
        with IndexBuilder(db_path) as builder:
            builder.add(row)
        with IndexBuilder(db_path) as builder:
            rows = list(builder.iter_rows())
        assert len(rows) == 1
        assert rows[0].source_path == "D:/music/file.mp3"
        assert rows[0].job_type == "convert"
        assert rows[0].is_lossy is True

    def test_add_many_inserts_rows(self, tmp_path: Path) -> None:
        """add_many() inserts multiple rows."""
        db_path = tmp_path / "test_index.db"
        rows = [
            IndexRow(
                source_path=f"D:/music/file{i}.mp3",
                dest_path=f"D:/output/file{i}.flac",
                job_type="convert",
                file_size=1000 + i,
                sidecar_files="",
                mtime=1000.0 + i,
                is_lossy=None,
            )
            for i in range(3)
        ]
        with IndexBuilder(db_path) as builder:
            builder.add_many(rows)
        with IndexBuilder(db_path) as builder:
            result = list(builder.iter_rows())
        assert len(result) == 3
        assert all(r.job_type == "convert" for r in result)

    def test_iter_rows_empty_returns_nothing(self, tmp_path: Path) -> None:
        """iter_rows on an empty table yields nothing."""
        db_path = tmp_path / "test_index.db"
        with IndexBuilder(db_path) as builder:
            result = list(builder.iter_rows())
        assert result == []

    def test_migration_adds_is_lossy_to_old_table(self, tmp_path: Path) -> None:
        """Creating a table without is_lossy then re-opening migrates it correctly."""
        db_path = tmp_path / "test_index.db"

        # Simulate an old table (no is_lossy column).
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE index_entries ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    source_path TEXT NOT NULL,"
            "    dest_path TEXT NOT NULL,"
            "    job_type TEXT NOT NULL,"
            "    file_size INTEGER NOT NULL,"
            "    sidecar_files TEXT NOT NULL,"
            "    mtime REAL NOT NULL,"
            "    created_at TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT INTO index_entries "
            "(source_path, dest_path, job_type, file_size, sidecar_files, mtime, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("D:/old/file.mp3", "D:/out/file.flac", "convert", 1000, "", 0.0, "2024-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        # Re-open with IndexBuilder — migration should add is_lossy without crashing.
        with IndexBuilder(db_path) as builder:
            cur = builder._conn.execute("PRAGMA table_info(index_entries)")
            cols = {row[1] for row in cur.fetchall()}
        assert "is_lossy" in cols

        # Old rows are still readable.
        with IndexBuilder(db_path) as builder:
            rows = list(builder.iter_rows())
        assert len(rows) == 1
        assert rows[0].source_path == "D:/old/file.mp3"
        # is_lossy is None for pre-migration rows (column is NULL).
        assert rows[0].is_lossy is None

    def test_migration_idempotent_on_fresh_table(self, tmp_path: Path) -> None:
        """Re-opening a table that already has is_lossy does not fail."""
        db_path = tmp_path / "test_index.db"
        with IndexBuilder(db_path) as builder:
            builder.add(
                IndexRow(
                    source_path="D:/music/file.mp3",
                    dest_path="D:/output/file.flac",
                    job_type="convert",
                    file_size=1000,
                    sidecar_files="",
                    mtime=0.0,
                    is_lossy=False,
                )
            )
        # Open again — should not raise.
        with IndexBuilder(db_path) as builder:
            cur = builder._conn.execute("PRAGMA table_info(index_entries)")
            cols = {row[1] for row in cur.fetchall()}
        assert "is_lossy" in cols

    def test_add_buffers_and_flushes_via_context_manager(self, tmp_path: Path) -> None:
        """A single add() inside ``with`` must be visible on next open (auto-flushed on exit)."""
        db_path = tmp_path / "test_index.db"
        with IndexBuilder(db_path) as builder:
            builder.add(
                IndexRow(
                    source_path="D:/music/buffered.mp3",
                    dest_path="D:/out/buffered.flac",
                    job_type="convert",
                    file_size=2048,
                    sidecar_files="",
                    mtime=1.0,
                    is_lossy=True,
                )
            )
        with IndexBuilder(db_path) as builder:
            rows = list(builder.iter_rows())
        assert len(rows) == 1
        assert rows[0].source_path == "D:/music/buffered.mp3"

    def test_add_auto_flushes_at_batch_size(self, tmp_path: Path) -> None:
        """After exactly ``_BATCH_SIZE`` adds, data must be on disk (committed)."""
        db_path = tmp_path / "test_index.db"
        batch_size = IndexBuilder._BATCH_SIZE
        with IndexBuilder(db_path) as builder:
            for i in range(batch_size):
                builder.add(
                    IndexRow(
                        source_path=f"D:/music/b{i}.mp3",
                        dest_path=f"D:/out/b{i}.flac",
                        job_type="convert",
                        file_size=i,
                        sidecar_files="",
                        mtime=0.0,
                        is_lossy=False,
                    )
                )
            # Without explicit commit, the batch boundary should have flushed.
            rows_mid = list(builder.iter_rows())
        assert len(rows_mid) == batch_size

    def test_commit_flushes_pending_buffer(self, tmp_path: Path) -> None:
        """commit() forces a flush of any buffered rows."""
        db_path = tmp_path / "test_index.db"
        builder = IndexBuilder(db_path)
        try:
            builder.add(
                IndexRow(
                    source_path="D:/music/c.mp3",
                    dest_path="D:/out/c.flac",
                    job_type="convert",
                    file_size=1,
                    sidecar_files="",
                    mtime=0.0,
                    is_lossy=None,
                )
            )
            builder.commit()
            rows = list(builder.iter_rows())
            assert len(rows) == 1
        finally:
            builder.close()

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        """IndexBuilder opens in WAL journal mode for fast bulk inserts."""
        db_path = tmp_path / "test_index.db"
        with IndexBuilder(db_path) as builder:
            mode = builder._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
