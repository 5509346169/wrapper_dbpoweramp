"""tests/test_tmp_staging.py: Unit tests for the tmp-staging long-path helper.

These tests cover the pure-Python portion of ``src.pathing.long_path``:
the opt-in toggle, the staging decision logic, the ``unstage()`` move semantics,
and the ``cleanup_staging_workspace()`` housekeeping.

The core staging logic is delegated to ``src.pathing.md5_staging``;
additional tests for that module live in ``tests/test_md5_staging.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.pathing.long_path import (
    StagingResult,
    _MAX_PATH_SAFE,
    _path_is_long,
    cleanup_staging_workspace,
    compute_md5sum,
    stage_paths,
    unstage,
)


# ---------------------------------------------------------------------------
# Threshold heuristic
# ---------------------------------------------------------------------------


class TestPathIsLong:
    """The ``_path_is_long`` heuristic decides whether to apply staging."""

    def test_short_path_under_threshold(self) -> None:
        assert _path_is_long(Path("C:/short/path/file.m4a")) is False

    def test_exactly_at_threshold_is_short(self) -> None:
        p = "C:/" + "a" * (_MAX_PATH_SAFE - 3)
        assert len(p) == _MAX_PATH_SAFE
        assert _path_is_long(Path(p)) is False

    def test_just_over_threshold_is_long(self) -> None:
        p = "C:/" + "a" * (_MAX_PATH_SAFE - 2)
        assert len(p) == _MAX_PATH_SAFE + 1
        assert _path_is_long(Path(p)) is True

    def test_unicode_path_length_uses_codepoints(self) -> None:
        p = Path("C:/" + ("鏡" * 200))
        assert len(str(p)) == 203
        assert _path_is_long(p) is False


# ---------------------------------------------------------------------------
# Opt-in toggle
# ---------------------------------------------------------------------------


class TestStagingDisabled:
    """When the user hasn't opted in, staging must be a no-op."""

    def test_disabled_returns_long_paths_unchanged(self, tmp_path: Path) -> None:
        long = tmp_path / ("a" * 200) / "in.m4a"
        long.parent.mkdir(parents=True, exist_ok=True)
        long.write_bytes(b"x")

        target = long.with_suffix(".out.m4a")
        r = stage_paths(long, target, enabled=False, tmp_root=tmp_path / "stage")
        assert r.staged is False
        assert r.staged_infile == long
        assert r.staged_outfile == target
        assert r.long_outfile == target

    def test_unstage_returns_true_when_not_staged(self, tmp_path: Path) -> None:
        """unstage() with staged=False must NOT touch the disk and return True."""
        long_out = tmp_path / "out.m4a"
        long_out.write_bytes(b"hello")

        r = StagingResult(
            long_infile=tmp_path / "in.m4a",
            long_outfile=long_out,
            staged_infile=tmp_path / "in.m4a",
            staged_outfile=long_out,
            staged=False,
            md5sum="abcd123456ef",
            temp_filename="",
        )
        assert unstage(r) is True


# ---------------------------------------------------------------------------
# Staging decision logic (via md5_staging delegation)
# ---------------------------------------------------------------------------


class TestStagingEnabled:
    """When enabled, staging kicks in for UTF-8 or long paths."""

    def test_short_ascii_path_skips_even_when_enabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A short ASCII path on win32 with auto mode must NOT trigger staging."""
        monkeypatch.setattr(sys, "platform", "win32")
        infile = tmp_path / "in.m4a"
        outfile = tmp_path / "out.m4a"
        infile.touch()

        r = stage_paths(infile, outfile, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False
        assert r.staged_infile == infile
        assert r.staged_outfile == outfile

    def test_utf8_name_stages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-ASCII filename triggers staging."""
        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"

        r = stage_paths(src, dst, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is True
        assert ".md5hash." in r.temp_filename

    def test_long_path_stages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When enabled and a path is long (>240 chars), the source is copied."""
        monkeypatch.setattr(sys, "platform", "win32")
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source content")

        stage_root = tmp_path / "stage"
        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)

        assert r.staged is True
        assert r.long_infile == long_in
        assert r.long_outfile == long_out
        assert r.staged_infile.parent == stage_root / "src"
        assert r.staged_outfile.parent == stage_root / "dst"
        assert r.staged_infile.name == r.staged_outfile.name
        assert r.staged_infile.name.endswith(".m4a")
        assert r.staged_infile.exists()
        assert r.staged_infile.read_bytes() == b"source content"

    def test_staged_basename_unique_per_source(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two source files with the same leaf name produce distinct staged paths."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in_1 = tmp_path / ("x" * 200) / "track01.m4a"
        long_in_2 = tmp_path / ("y" * 200) / "track01.m4a"
        long_out_1 = tmp_path / ("x" * 200) / "track01.m4a"
        long_out_2 = tmp_path / ("y" * 200) / "track01.m4a"
        for p in (long_in_1, long_in_2):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"data")

        r1 = stage_paths(long_in_1, long_out_1, enabled=True, tmp_root=stage_root)
        r2 = stage_paths(long_in_2, long_out_2, enabled=True, tmp_root=stage_root)

        assert r1.staged_infile != r2.staged_infile
        assert r1.staged_outfile != r2.staged_outfile
        assert r1.staged_infile.exists()
        assert r2.staged_infile.exists()

    def test_md5sum_always_populated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Result.md5sum is always set, even when staged=False."""
        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "a.flac"
        src.touch()
        dst = tmp_path / "b.flac"
        r = stage_paths(src, dst, enabled=False)
        assert r.md5sum != ""
        assert len(r.md5sum) == 12

    def test_source_copy_failure_falls_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the source file is missing, staged=False is returned."""
        monkeypatch.setattr(sys, "platform", "win32")
        long_in = tmp_path / ("a" * 200) / "nonexistent.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out = tmp_path / ("a" * 200) / "out.m4a"

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False


# ---------------------------------------------------------------------------
# unstage() — atomic rename / copy semantics
# ---------------------------------------------------------------------------


class TestUnstage:
    """unstage() transfers the staged output to the long destination then cleans up."""

    def test_successful_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-empty staged output is transferred to the long destination;
        both staged artefacts are cleaned up."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        assert r.staged is True
        r.staged_outfile.write_bytes(b"converted audio")

        assert unstage(r) is True
        assert long_out.exists()
        assert long_out.read_bytes() == b"converted audio"
        assert not r.staged_infile.exists()
        assert not r.staged_outfile.exists()

    def test_missing_staged_output_returns_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing staged output returns False."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")
        long_out.parent.mkdir(parents=True, exist_ok=True)

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        assert r.staged is True
        # staged_outfile was never written to
        assert unstage(r) is False
        assert not long_out.exists()
        assert not r.staged_infile.exists()

    def test_empty_staged_output_returns_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 0-byte staged output (qaac-pipe-failure symptom) returns False."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"")  # 0 bytes

        assert unstage(r) is False
        assert not r.staged_outfile.exists()
        assert not long_out.exists()

    def test_existing_long_destination_is_overwritten(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-existing destination is overwritten."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")
        long_out.write_bytes(b"OLD STALE OUTPUT")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"new fresh output")

        assert unstage(r) is True
        assert long_out.read_bytes() == b"new fresh output"

    def test_unstage_creates_missing_parent_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the long-destination's parent dir was deleted, unstage() creates it."""
        monkeypatch.setattr(sys, "platform", "win32")
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")
        # Note: long_out.parent deliberately not created.

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"data")

        assert unstage(r) is True
        assert long_out.exists()
        assert long_out.read_bytes() == b"data"


# ---------------------------------------------------------------------------
# Property aliases and new fields
# ---------------------------------------------------------------------------


class TestStagingResultFields:
    """StagingResult always carries md5sum and temp_filename."""

    def test_infile_outfile_alias(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """infile/outfile aliases work."""
        monkeypatch.setattr(sys, "platform", "win32")
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.infile == r.staged_infile
        assert r.outfile == r.staged_outfile

    def test_md5sum_always_set(self, tmp_path: Path) -> None:
        """md5sum is always present even when staged=False."""
        r = StagingResult(
            long_infile=tmp_path / "a.flac",
            long_outfile=tmp_path / "b.flac",
            staged_infile=tmp_path / "a.flac",
            staged_outfile=tmp_path / "b.flac",
            staged=False,
            md5sum="abcd123456ef",
            temp_filename="",
        )
        assert r.md5sum == "abcd123456ef"
        assert len(r.md5sum) == 12


# ---------------------------------------------------------------------------
# compute_md5sum re-exported from long_path
# ---------------------------------------------------------------------------


class TestComputeMd5sumExport:
    """compute_md5sum is re-exported from long_path for convenience."""

    def test_re_exported(self) -> None:
        assert callable(compute_md5sum)

    def test_deterministic(self, tmp_path: Path) -> None:
        p = tmp_path / "music" / "track.flac"
        h1 = compute_md5sum(p)
        h2 = compute_md5sum(p)
        assert h1 == h2
        assert len(h1) == 12

    def test_utf8_path(self, tmp_path: Path) -> None:
        p = tmp_path / "日本語" / "track.flac"
        h = compute_md5sum(p)
        assert len(h) == 12


# ---------------------------------------------------------------------------
# cleanup_staging_workspace
# ---------------------------------------------------------------------------


class TestCleanupStagingWorkspace:
    """The startup cleanup helper clears leftover files from previous runs."""

    def test_clears_src_and_dst(self, tmp_path: Path) -> None:
        stage_root = tmp_path / "audio"
        for sub in ("src", "dst"):
            d = stage_root / sub
            d.mkdir(parents=True)
            (d / "leftover.m4a").write_bytes(b"stale")

        cleanup_staging_workspace(tmp_root=stage_root)

        assert list((stage_root / "src").iterdir()) == []
        assert list((stage_root / "dst").iterdir()) == []

    def test_missing_dirs_are_no_op(self, tmp_path: Path) -> None:
        cleanup_staging_workspace(tmp_root=tmp_path / "does_not_exist")

    def test_subdirectory_inside_src_is_removed(self, tmp_path: Path) -> None:
        stage_root = tmp_path / "audio"
        nested = stage_root / "src" / "nested-dir"
        nested.mkdir(parents=True)
        (nested / "file.m4a").write_bytes(b"x")

        cleanup_staging_workspace(tmp_root=stage_root)

        assert not nested.exists()
        assert not (stage_root / "src" / "nested-dir").exists()


# ---------------------------------------------------------------------------
# md5_staging mode parameter
# ---------------------------------------------------------------------------


class TestMd5StagingMode:
    """The md5_staging parameter controls the naming form of staged files."""

    def test_auto_uses_md5hash_form(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """auto mode uses the <md5>.md5hash.<ext> form."""
        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"

        r = stage_paths(src, dst, enabled=True, tmp_root=tmp_path / "stage", md5_staging="auto")
        assert r.staged is True
        assert ".md5hash." in r.temp_filename
        assert r.temp_filename.endswith(".md5hash.flac")

    def test_on_uses_md5hash_form(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """on mode uses the <md5>.md5hash.<ext> form."""
        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "track.flac"
        src.touch()
        dst = tmp_path / "output.flac"

        r = stage_paths(src, dst, enabled=True, tmp_root=tmp_path / "stage", md5_staging="on")
        assert r.staged is True
        assert ".md5hash." in r.temp_filename

    def test_off_uses_legacy_form(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """off mode uses the legacy <8-hex>__<basename> form."""
        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"

        r = stage_paths(src, dst, enabled=True, tmp_root=tmp_path / "stage", md5_staging="off")
        assert r.staged is True
        assert "__" in r.temp_filename
        assert ".md5hash." not in r.temp_filename
        assert r.temp_filename.endswith("__output.flac")


# ---------------------------------------------------------------------------
# Cross-platform behaviour
# ---------------------------------------------------------------------------


class TestCrossPlatform:
    """Non-Windows platforms skip staging entirely."""

    def test_non_win32_always_returns_staged_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"

        r = stage_paths(src, dst, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False
