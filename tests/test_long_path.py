"""tests/test_long_path.py: Unit tests for the long-path staging helper.

These tests cover the pure-Python portion of ``src.pathing.long_path``:
the threshold heuristic, the opt-in toggle, and the staging decision logic
itself. The Win32 ``GetShortPathNameW`` resolution is mocked so the tests
run on any platform.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pathing.long_path import (
    _MAX_PATH_SAFE,
    StagingResult,
    _path_is_long,
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
        # Threshold is exclusive (>, not >=), so exactly _MAX_PATH_SAFE
        # characters must not trigger staging. "C:/" is 3 chars.
        p = "C:/" + "a" * (_MAX_PATH_SAFE - 3)
        assert len(p) == _MAX_PATH_SAFE
        assert _path_is_long(Path(p)) is False

    def test_just_over_threshold_is_long(self) -> None:
        p = "C:/" + "a" * (_MAX_PATH_SAFE - 2)
        assert len(p) == _MAX_PATH_SAFE + 1
        assert _path_is_long(Path(p)) is True

    def test_unicode_path_length_uses_codepoints(self) -> None:
        # 200 CJK chars (each a single Python str codepoint but multi-byte
        # in UTF-16). The threshold is character-count, not byte-count.
        p = Path("C:/" + ("鏡" * 200))
        # "C:/" = 3 chars + 200 CJK chars = 203
        assert len(str(p)) == 203
        assert _path_is_long(p) is False


# ---------------------------------------------------------------------------
# Opt-in toggle
# ---------------------------------------------------------------------------


class TestStagingDisabled:
    """When the user hasn't opted in, staging must be a no-op."""

    def test_disabled_returns_long_paths_unchanged(self, tmp_path: Path) -> None:
        infile = tmp_path / "in.m4a"
        outfile = tmp_path / "out.m4a"
        # Even a path "long enough" to trigger staging must pass through
        # unchanged when enabled=False.
        long = tmp_path / ("a" * 200) / "in.m4a"
        long.parent.mkdir(parents=True, exist_ok=True)
        long.touch()

        r = stage_paths(long, long.with_suffix(".out.m4a"), enabled=False)
        assert r.staged is False
        assert r.infile == long
        assert r.outfile == long.with_suffix(".out.m4a")
        assert r.long_outfile == long.with_suffix(".out.m4a")

    def test_unstage_returns_true_when_not_staged(self, tmp_path: Path) -> None:
        """unstage() with staged=False must be a no-op that returns True."""
        r = StagingResult(
            infile=tmp_path / "in.m4a",
            outfile=tmp_path / "out.m4a",
            staged=False,
            long_outfile=tmp_path / "out.m4a",
        )
        assert unstage(r) is True


# ---------------------------------------------------------------------------
# Staging decision logic (with mocked Win32 short-path resolution)
# ---------------------------------------------------------------------------


class TestStagingEnabled:
    """When enabled, staging kicks in iff the path is long AND a short
    form is available."""

    def test_short_path_skips_even_when_enabled(
        self,
        tmp_path: Path,
    ) -> None:
        """A path under the threshold must NOT trigger staging even when
        enabled=True — avoids unnecessary mkdir + GetShortPathNameW calls
        on the happy path."""
        infile = tmp_path / "in.m4a"
        outfile = tmp_path / "out.m4a"

        r = stage_paths(infile, outfile, enabled=True)
        assert r.staged is False
        assert r.infile == infile

    def test_long_path_with_resolved_short_name_stages(
        self,
        tmp_path: Path,
    ) -> None:
        """When enabled and a long path resolves to a short path, the
        StagingResult carries the short forms and staged=True."""
        infile = tmp_path / ("a" * 200) / "in.m4a"
        outfile = tmp_path / ("a" * 200) / "out.m4a"
        infile.parent.mkdir(parents=True, exist_ok=True)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        infile.touch()

        long_str = str(infile)
        # WindowsPath normalises forward slashes to backslashes in str(),
        # so the short string should use backslashes to match.
        short_str = "C:\\short\\in.m4a"
        assert len(short_str) < len(long_str)

        with patch(
            "src.pathing.long_path._get_short_path_name_windows",
            return_value=short_str,
        ):
            r = stage_paths(infile, outfile, enabled=True)

        assert r.staged is True
        assert str(r.infile) == short_str
        assert r.long_outfile == outfile

    def test_long_path_with_unresolved_short_name_falls_back(
        self,
        tmp_path: Path,
    ) -> None:
        """If Win32 can't resolve the short name (path missing, 8.3 disabled,
        etc.), the helper falls back to the long path. Better to surface
        CoreConverter's own error than to silently claim staging succeeded."""
        infile = tmp_path / ("a" * 200) / "in.m4a"
        outfile = tmp_path / ("a" * 200) / "out.m4a"
        infile.parent.mkdir(parents=True, exist_ok=True)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        infile.touch()

        with patch(
            "src.pathing.long_path._get_short_path_name_windows",
            return_value=None,
        ):
            r = stage_paths(infile, outfile, enabled=True)

        assert r.staged is False
        assert r.infile == infile
        assert r.outfile == outfile

    def test_short_name_unchanged_falls_back(
        self,
        tmp_path: Path,
    ) -> None:
        """If GetShortPathNameW returns the input unchanged (volume has
        8.3 names disabled), we must NOT claim staged=True — that would
        confuse the caller into expecting a rename from a path that
        doesn't exist."""
        infile = tmp_path / ("a" * 200) / "in.m4a"
        outfile = tmp_path / ("a" * 200) / "out.m4a"
        infile.parent.mkdir(parents=True, exist_ok=True)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        infile.touch()

        # Simulate 8.3 disabled: GetShortPathNameW echoes the input.
        with patch(
            "src.pathing.long_path._get_short_path_name_windows",
            side_effect=lambda p: p,
        ):
            r = stage_paths(infile, outfile, enabled=True)

        assert r.staged is False


# ---------------------------------------------------------------------------
# Non-Windows behaviour
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
class TestNonWindowsBehaviour:
    """On Linux/macOS, GetShortPathNameW does not exist; staging is a no-op."""

    def test_non_windows_skips_staging(self, tmp_path: Path) -> None:
        infile = tmp_path / ("a" * 200) / "in.m4a"
        outfile = tmp_path / ("a" * 200) / "out.m4a"
        infile.parent.mkdir(parents=True, exist_ok=True)

        r = stage_paths(infile, outfile, enabled=True)
        assert r.staged is False


# ---------------------------------------------------------------------------
# unstage() move semantics
# ---------------------------------------------------------------------------


class TestUnstage:
    """unstage() checks that the long-path output now exists after staging.

    On NTFS the short and long paths share an inode, so CoreConverter's
    write to the short path is already visible at the long path — there is
    nothing to move. unstage() is a verification, not a rename."""

    def test_successful_check(self, tmp_path: Path) -> None:
        """If the long-path output exists and is non-empty, unstage() returns True."""
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_out.write_bytes(b"x" * 100)

        r = StagingResult(
            infile=tmp_path / "in.m4a",
            outfile=tmp_path / "short" / "out.m4a",
            staged=True,
            long_outfile=long_out,
        )
        assert unstage(r) is True

    def test_missing_long_output_returns_false(self, tmp_path: Path) -> None:
        """If the long-path output is missing, unstage() returns False —
        CoreConverter probably failed mid-write."""
        r = StagingResult(
            infile=tmp_path / "in.m4a",
            outfile=tmp_path / "short" / "out.m4a",
            staged=True,
            long_outfile=tmp_path / ("a" * 200) / "out.m4a",  # doesn't exist
        )
        assert unstage(r) is False

    def test_empty_long_output_returns_false(self, tmp_path: Path) -> None:
        """If the long-path output is empty, unstage() returns False —
        CoreConverter produced a 0-byte file (the same symptom as the
        original long-path bug if short-name resolution didn't help)."""
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_out.write_bytes(b"")

        r = StagingResult(
            infile=tmp_path / "in.m4a",
            outfile=tmp_path / "short" / "out.m4a",
            staged=True,
            long_outfile=long_out,
        )
        assert unstage(r) is False