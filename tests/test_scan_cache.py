"""tests/test_scan_cache.py: Tests for the per-run scan-cache SQLite snapshot."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.index.scan_cache import (
    SCAN_CACHE_PREFIX,
    SCAN_CACHE_SUFFIX,
    ScanCache,
    cache_filename_for_run,
    _compute_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input_dir(tmp_path: Path, n_files: int = 5) -> Path:
    """Create a temp input directory with ``n_files`` dummy .mp3 files."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        (tmp_path / f"track_{i:03d}.mp3").write_bytes(b"\x00" * 1024)
    return tmp_path


# ---------------------------------------------------------------------------
# cache_filename_for_run
# ---------------------------------------------------------------------------

class TestCacheFilenameForRun:
    """Tests for the cache filename generator."""

    def test_filename_has_expected_prefix_suffix(self, tmp_path: Path) -> None:
        name = cache_filename_for_run(tmp_path, [])
        assert name.startswith(SCAN_CACHE_PREFIX)
        assert name.endswith(SCAN_CACHE_SUFFIX)

    def test_filename_contains_signature_and_ts_hash(self, tmp_path: Path) -> None:
        name = cache_filename_for_run(tmp_path, ["exclude_me"])
        # Prefix + ts_hash + _ + sig + suffix
        stem = name[len(SCAN_CACHE_PREFIX):-len(SCAN_CACHE_SUFFIX)]
        parts = stem.split("_")
        assert len(parts) == 2
        assert len(parts[0]) == 12  # md5(ts)[:12]
        assert len(parts[1]) == 16  # sha256(input|excludes)[:16]

    def test_filename_changes_per_run_timestamp(self, tmp_path: Path) -> None:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
        n1 = cache_filename_for_run(tmp_path, [], now=t1)
        n2 = cache_filename_for_run(tmp_path, [], now=t2)
        assert n1 != n2

    def test_filename_same_for_same_input_excludes_within_run(self, tmp_path: Path) -> None:
        t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        n1 = cache_filename_for_run(tmp_path, ["a", "b"], now=t)
        n2 = cache_filename_for_run(tmp_path, ["b", "a"], now=t)
        # excludes order doesn't matter — sorted internally.
        assert n1 == n2


# ---------------------------------------------------------------------------
# _compute_signature
# ---------------------------------------------------------------------------

class TestComputeSignature:
    """The signature is the cross-run reuse key."""

    def test_same_input_same_excludes_same_signature(self, tmp_path: Path) -> None:
        s1 = _compute_signature(tmp_path, ["a"])
        s2 = _compute_signature(tmp_path, ["a"])
        assert s1 == s2

    def test_excludes_order_does_not_matter(self, tmp_path: Path) -> None:
        s1 = _compute_signature(tmp_path, ["a", "b"])
        s2 = _compute_signature(tmp_path, ["b", "a"])
        assert s1 == s2

    def test_different_excludes_different_signature(self, tmp_path: Path) -> None:
        s1 = _compute_signature(tmp_path, ["a"])
        s2 = _compute_signature(tmp_path, ["a", "extra"])
        assert s1 != s2

    def test_signature_is_resolved_path_independent(self, tmp_path: Path) -> None:
        # Same logical path, accessed via different relative strings,
        # should produce the same signature after .resolve().
        s1 = _compute_signature(tmp_path / "subdir", [])
        s2 = _compute_signature(tmp_path / "subdir", [])
        assert s1 == s2


# ---------------------------------------------------------------------------
# ScanCache.create / add / commit / iter_files / count / meta
# ---------------------------------------------------------------------------

class TestScanCacheCreate:
    def test_create_makes_file_in_tmp_dir(self, tmp_path: Path) -> None:
        _make_input_dir(tmp_path)
        cache = ScanCache.create(tmp_path, tmp_path, [])
        try:
            assert cache.db_path.exists()
            assert cache.db_path.parent == tmp_path
            assert cache.db_path.name.startswith(SCAN_CACHE_PREFIX)
        finally:
            cache.close()

    def test_create_no_staging_file_left_behind(self, tmp_path: Path) -> None:
        _make_input_dir(tmp_path)
        cache = ScanCache.create(tmp_path, tmp_path, [])
        try:
            staging = list(tmp_path.glob(f"{SCAN_CACHE_PREFIX}*.staging"))
            assert staging == []
        finally:
            cache.close()

    def test_create_stamps_meta_row(self, tmp_path: Path) -> None:
        input_path = _make_input_dir(tmp_path)
        cache = ScanCache.create(input_path, input_path, ["a", "b"])
        try:
            meta = cache.meta()
            assert meta["input_signature"] == _compute_signature(input_path, ["a", "b"])
            assert meta["input_path"] == str(input_path.resolve())
            assert meta["excludes"] == "a,b"  # sorted
            assert "created_at" in meta
        finally:
            cache.close()

    def test_add_and_iter_files(self, tmp_path: Path) -> None:
        input_path = _make_input_dir(tmp_path, n_files=4)
        cache = ScanCache.create(input_path, input_path, [])
        try:
            cache.add("D:/music/a.mp3", 1024, 1234.5, "")
            cache.add("D:/music/b.mp3", 2048, 1234.6, "b.lrc")
            cache.commit()
            rows = list(cache.iter_files())
            assert len(rows) == 2
            assert rows[0][0] == "D:/music/a.mp3"
            assert rows[0][1] == 1024
            assert rows[0][2] == 1234.5
            assert rows[0][3] == ""
            assert rows[1][0] == "D:/music/b.mp3"
            assert rows[1][3] == "b.lrc"
            assert cache.count() == 2
        finally:
            cache.close()

    def test_add_is_idempotent_via_insert_or_replace(self, tmp_path: Path) -> None:
        """Re-adding the same path with different sizes should update, not duplicate."""
        input_path = _make_input_dir(tmp_path)
        cache = ScanCache.create(input_path, input_path, [])
        try:
            cache.add("D:/music/a.mp3", 100, 1.0, "")
            cache.commit()
            cache.add("D:/music/a.mp3", 200, 2.0, "a.lrc")
            cache.commit()
            assert cache.count() == 1
            rows = list(cache.iter_files())
            assert rows[0][1] == 200  # new size
            assert rows[0][2] == 2.0
            assert rows[0][3] == "a.lrc"
        finally:
            cache.close()


# ---------------------------------------------------------------------------
# ScanCache.open_latest
# ---------------------------------------------------------------------------

class TestScanCacheOpenLatest:
    def test_returns_none_when_no_cache_files(self, tmp_path: Path) -> None:
        # tmp_path exists but is empty.
        result = ScanCache.open_latest(tmp_path, tmp_path, [])
        assert result is None

    def test_returns_none_when_tmp_dir_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "no_such_dir"
        result = ScanCache.open_latest(nonexistent, tmp_path, [])
        assert result is None

    def test_returns_none_when_signature_mismatch(self, tmp_path: Path) -> None:
        """A cache for input A should not match a request for input B."""
        input_a = _make_input_dir(tmp_path / "a", n_files=3)
        cache = ScanCache.create(input_a, input_a, [])
        cache.close()
        # Now ask for a different input.
        input_b = tmp_path / "b"
        input_b.mkdir()
        result = ScanCache.open_latest(tmp_path, input_b, [])
        assert result is None

    def test_returns_none_when_excludes_mismatch(self, tmp_path: Path) -> None:
        input_path = _make_input_dir(tmp_path)
        cache = ScanCache.create(input_path, input_path, ["excluded"])
        cache.close()
        result = ScanCache.open_latest(tmp_path, input_path, ["different"])
        assert result is None

    def test_returns_cache_when_signature_matches(self, tmp_path: Path) -> None:
        input_path = _make_input_dir(tmp_path, n_files=3)
        original = ScanCache.create(input_path, input_path, [])
        original.add("D:/music/x.mp3", 999, 1.0, "x.lrc")
        original.commit()
        original.close()

        reopened = ScanCache.open_latest(tmp_path, input_path, [])
        try:
            assert reopened is not None
            assert reopened.meta()["input_signature"] == _compute_signature(input_path, [])
            rows = list(reopened.iter_files())
            assert len(rows) == 1
            assert rows[0][0] == "D:/music/x.mp3"
            assert rows[0][1] == 999
        finally:
            reopened.close()

    def test_skips_staging_files(self, tmp_path: Path) -> None:
        """Half-written staging files must never be picked up."""
        input_path = _make_input_dir(tmp_path)
        ScanCache.create(input_path, input_path, []).close()
        # Drop a fake staging file alongside it.
        staging = tmp_path / f"{SCAN_CACHE_PREFIX}fake123_staging{SCAN_CACHE_SUFFIX}.staging"
        staging.write_bytes(b"not a sqlite db")
        result = ScanCache.open_latest(tmp_path, input_path, [])
        assert result is not None
        # It should have returned the real cache, not the staging one.
        assert not result.db_path.name.endswith(".staging")
        result.close()

    def test_returns_none_when_cache_corrupt(self, tmp_path: Path) -> None:
        """A non-SQLite file matching the pattern is silently skipped."""
        bogus = tmp_path / f"{SCAN_CACHE_PREFIX}bogus_{'a' * 16}{SCAN_CACHE_SUFFIX}"
        bogus.write_bytes(b"not a sqlite db")
        result = ScanCache.open_latest(tmp_path, tmp_path, [])
        assert result is None


# ---------------------------------------------------------------------------
# Integration: write via add() then read via open_latest()
# ---------------------------------------------------------------------------

class TestScanCacheRoundTrip:
    def test_full_round_trip_preserves_all_fields(self, tmp_path: Path) -> None:
        input_path = _make_input_dir(tmp_path, n_files=5)
        rows = [
            ("D:/music/{}.flac".format(i), 1024 * (i + 1), float(i), f"side{i}.lrc")
            for i in range(5)
        ]
        writer = ScanCache.create(input_path, input_path, ["exclude_me"])
        for path, size, mtime, sidecar in rows:
            writer.add(path, size, mtime, sidecar)
        writer.commit()
        writer.close()

        reader = ScanCache.open_latest(tmp_path, input_path, ["exclude_me"])
        try:
            assert reader is not None
            reloaded = list(reader.iter_files())
            assert len(reloaded) == 5
            for (expected_path, expected_size, expected_mtime, expected_sidecar), got in zip(
                rows, reloaded
            ):
                assert got[0] == expected_path
                assert got[1] == expected_size
                assert got[2] == expected_mtime
                assert got[3] == expected_sidecar
        finally:
            reader.close()

    def test_load_rows_from_cache_works(self, tmp_path: Path) -> None:
        """Integration with the higher-level helper used by main.py."""
        from src.index.scanner import load_rows_from_cache

        input_path = _make_input_dir(tmp_path, n_files=2)
        cache = ScanCache.create(input_path, input_path, [])
        cache.add("D:/music/track.mp3", 4096, 100.5, "track.lrc")
        cache.add("D:/music/track2.mp3", 8192, 200.5, "")
        cache.commit()

        rows = load_rows_from_cache(cache)
        assert len(rows) == 2
        assert rows[0].source_path == "D:/music/track.mp3"
        assert rows[0].file_size == 4096
        assert rows[0].mtime == 100.5
        assert rows[0].sidecar_files == "track.lrc"
        # IndexRow fields not populated by the cache must be empty defaults.
        assert rows[0].dest_path == ""
        assert rows[0].job_type == ""
        assert rows[0].is_lossy is None
        cache.close()