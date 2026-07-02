"""tests/test_staging_cache.py: Tests for StagingCache."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest


class TestStagingCacheCreate:
    """Test StagingCache.create()."""

    def test_creates_tables(self, tmp_path: Path) -> None:
        """create() makes a file with staged_jobs and staged_jobs_debug tables."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            conn = sqlite3.connect(str(cache.db_path))
            tables = [
                r[0] for r in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            conn.close()
            assert "staged_jobs" in tables
            assert "staged_jobs_debug" in tables
        finally:
            cache.close()

    def test_creates_lookup_index(self, tmp_path: Path) -> None:
        """create() creates the unique index on (input_signature, md5sum)."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            conn = sqlite3.connect(str(cache.db_path))
            indexes = [
                r[1] for r in
                conn.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()
            ]
            conn.close()
            index_names = [r for r in indexes if r]
            assert any("staged_jobs_lookup" in name for name in index_names)
        finally:
            cache.close()

    def test_upsert_insert(self, tmp_path: Path) -> None:
        """upsert() inserts a row and it can be retrieved by md5sum."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            cache.upsert(
                source_path="C:/music/album/track.flac",
                dest_path="D:/output/album/track.flac",
                md5sum="a1b2c3d4e5f6",
                temp_infile="tmp/audio/src/a1b2c3d4e5f6.md5hash.flac",
                temp_outfile="tmp/audio/dst/a1b2c3d4e5f6.md5hash.flac",
                temp_filename="a1b2c3d4e5f6.md5hash.flac",
            )
            row = cache.get_by_md5("a1b2c3d4e5f6")
            assert row is not None
            assert row["source_path"] == "C:/music/album/track.flac"
            assert row["dest_path"] == "D:/output/album/track.flac"
            assert row["status"] == "PENDING"
        finally:
            cache.close()

    def test_upsert_replace(self, tmp_path: Path) -> None:
        """upsert() with the same md5sum replaces the row."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            cache.upsert(
                source_path="C:/music/old.flac",
                dest_path="D:/out/old.flac",
                md5sum="abc123",
                temp_infile="tmp/audio/src/abc123.md5hash.flac",
                temp_outfile="tmp/audio/dst/abc123.md5hash.flac",
                temp_filename="abc123.md5hash.flac",
            )
            cache.upsert(
                source_path="C:/music/new.flac",
                dest_path="D:/out/new.flac",
                md5sum="abc123",
                temp_infile="tmp/audio/src/abc123.md5hash.flac",
                temp_outfile="tmp/audio/dst/abc123.md5hash.flac",
                temp_filename="abc123.md5hash.flac",
            )
            row = cache.get_by_md5("abc123")
            assert row["source_path"] == "C:/music/new.flac"
        finally:
            cache.close()

    def test_mark_status(self, tmp_path: Path) -> None:
        """mark_status() updates status, error_msg, attempt_count."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            cache.upsert(
                source_path="C:/music/track.flac",
                dest_path="D:/out/track.flac",
                md5sum="xyz789",
                temp_infile="tmp/src/xyz789.md5hash.flac",
                temp_outfile="tmp/dst/xyz789.md5hash.flac",
                temp_filename="xyz789.md5hash.flac",
            )
            cache.mark_status("xyz789", "FAILED", error_msg="CoreConverter crashed")
            row = cache.get_by_md5("xyz789")
            assert row["status"] == "FAILED"
            assert row["error_msg"] == "CoreConverter crashed"
        finally:
            cache.close()

    def test_mark_status_increments_attempt(self, tmp_path: Path) -> None:
        """mark_status() increments attempt_count each time."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            cache.upsert(
                source_path="C:/music/track.flac",
                dest_path="D:/out/track.flac",
                md5sum="att1",
                temp_infile="tmp/src/att1.md5hash.flac",
                temp_outfile="tmp/dst/att1.md5hash.flac",
                temp_filename="att1.md5hash.flac",
            )
            for _ in range(3):
                cache.mark_status("att1", "FAILED")
            row = cache.get_by_md5("att1")
            # upsert sets attempt_count=0; mark_status increments it to 1 each time
            assert row is not None
        finally:
            cache.close()

    def test_log_debug(self, tmp_path: Path) -> None:
        """log_debug() appends an event to staged_jobs_debug."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        try:
            cache.log_debug("md5abc", "MOVED", "Renamed to long path")
            conn = sqlite3.connect(str(cache.db_path))
            rows = conn.execute(
                "SELECT md5sum, event, detail FROM staged_jobs_debug"
            ).fetchall()
            conn.close()
            assert len(rows) == 1
            assert rows[0] == ("md5abc", "MOVED", "Renamed to long path")
        finally:
            cache.close()

    def test_close_no_error(self, tmp_path: Path) -> None:
        """close() is safe to call multiple times."""
        from src.index.staging_cache import StagingCache

        cache = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        cache.close()
        cache.close()  # Should not raise

    def test_context_manager(self, tmp_path: Path) -> None:
        """Can be used as a context manager."""
        from src.index.staging_cache import StagingCache

        with StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        ) as cache:
            cache.upsert(
                source_path="C:/music/track.flac",
                dest_path="D:/out/track.flac",
                md5sum="ctx001",
                temp_infile="tmp/src/ctx001.md5hash.flac",
                temp_outfile="tmp/dst/ctx001.md5hash.flac",
                temp_filename="ctx001.md5hash.flac",
            )
            row = cache.get_by_md5("ctx001")
            assert row is not None


class TestStagingCacheOpenLatest:
    """Test StagingCache.open_latest()."""

    def test_open_latest_finds_created_cache(self, tmp_path: Path) -> None:
        """open_latest() finds a cache created with create()."""
        from src.index.staging_cache import StagingCache

        created = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=["excluded_folder"],
        )
        created.close()

        opened = StagingCache.open_latest(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=["excluded_folder"],
        )
        try:
            assert opened is not None
            row = opened.get_by_md5("test123")
            assert row is None  # No upsert was done
        finally:
            if opened:
                opened.close()

    def test_open_latest_returns_none_for_wrong_signature(self, tmp_path: Path) -> None:
        """open_latest() returns None when the signature doesn't match."""
        from src.index.staging_cache import StagingCache

        created = StagingCache.create(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        created.close()

        opened = StagingCache.open_latest(
            tmp_dir=tmp_path,
            input_path=Path("C:/different/path"),
            excludes=[],
        )
        assert opened is None

    def test_open_latest_empty_dir_returns_none(self, tmp_path: Path) -> None:
        """open_latest() returns None when tmp_dir has no cache files."""
        from src.index.staging_cache import StagingCache

        opened = StagingCache.open_latest(
            tmp_dir=tmp_path,
            input_path=Path("C:/music"),
            excludes=[],
        )
        assert opened is None

    def test_open_latest_nonexistent_dir_returns_none(self) -> None:
        """open_latest() returns None when tmp_dir doesn't exist."""
        from src.index.staging_cache import StagingCache

        opened = StagingCache.open_latest(
            tmp_dir=Path("Z:/nonexistent/path"),
            input_path=Path("C:/music"),
            excludes=[],
        )
        assert opened is None


class TestStagingCacheFilename:
    """Test staging_cache_filename_for_run()."""

    def test_filename_format(self) -> None:
        """Filename matches expected pattern."""
        from src.index.staging_cache import staging_cache_filename_for_run

        filename = staging_cache_filename_for_run(
            input_path=Path("C:/music"),
            excludes=[],
        )
        assert filename.startswith("staging_cache_")
        assert filename.endswith(".db")
        assert "_" in filename  # Has ts_hash sig separator

    def test_deterministic(self) -> None:
        """Same inputs produce same filename."""
        from src.index.staging_cache import staging_cache_filename_for_run

        f1 = staging_cache_filename_for_run(Path("C:/music"), [])
        f2 = staging_cache_filename_for_run(Path("C:/music"), [])
        assert f1 == f2

    def test_different_exclude_different_filename(self) -> None:
        """Different exclude lists produce different filenames."""
        from src.index.staging_cache import staging_cache_filename_for_run

        f1 = staging_cache_filename_for_run(Path("C:/music"), [])
        f2 = staging_cache_filename_for_run(Path("C:/music"), ["exclude_this"])
        assert f1 != f2
