"""tests/test_tmp_staging.py: Unit tests for the tmp-staging long-path helper.

These tests cover the pure-Python portion of ``src.pathing.long_path``:
the threshold heuristic, the opt-in toggle, the staging decision logic,
the ``unstage()`` move semantics, the unique-basename hash to handle
collisions, and the ``cleanup_staging_workspace()`` housekeeping.

Unlike the previous 8.3-short-name implementation, this module no longer
touches Win32 APIs at all, so all tests run unmodified on every
platform.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from src.pathing.long_path import (
    StagingResult,
    _MAX_PATH_SAFE,
    _path_is_long,
    _short_hash,
    cleanup_staging_workspace,
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
        # Even a path "long enough" to trigger staging must pass through
        # unchanged when enabled=False.
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
        )
        assert unstage(r) is True


# ---------------------------------------------------------------------------
# Staging decision logic
# ---------------------------------------------------------------------------


class TestStagingEnabled:
    """When enabled, staging kicks in iff the path is long enough."""

    def test_short_path_skips_even_when_enabled(
        self,
        tmp_path: Path,
    ) -> None:
        """A path under the threshold must NOT trigger staging even when
        enabled=True — avoids an unnecessary source copy on the happy path."""
        infile = tmp_path / "in.m4a"
        outfile = tmp_path / "out.m4a"

        r = stage_paths(infile, outfile, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False
        assert r.staged_infile == infile
        assert r.staged_outfile == outfile

    def test_long_path_stages(self, tmp_path: Path) -> None:
        """When enabled and a path is long, the source is copied under
        ``tmp_root/src/`` and the staged output goes under ``tmp_root/dst/``."""
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source content")

        stage_root = tmp_path / "stage"
        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)

        assert r.staged is True
        assert r.long_infile == long_in
        assert r.long_outfile == long_out
        # Staged paths live under the configured tmp_root.
        assert r.staged_infile.parent == stage_root / "src"
        assert r.staged_outfile.parent == stage_root / "dst"
        # Staged input and output share the same basename (a hash prefix
        # + the original outfile name) so CoreConverter's output lands at
        # a known location.
        assert r.staged_infile.name == r.staged_outfile.name
        assert r.staged_infile.name.endswith(".m4a")
        # The source was actually copied.
        assert r.staged_infile.exists()
        assert r.staged_infile.read_bytes() == b"source content"

    def test_staged_basename_is_unique_per_source(self, tmp_path: Path) -> None:
        """Two source files with the same leaf name (e.g. ``track01.m4a``
        in two different folders) must NOT collide in the staging tree —
        the hash prefix disambiguates them."""
        stage_root = tmp_path / "stage"
        # Build two long paths whose basenames match but whose full paths
        # differ.
        long_in_1 = tmp_path / ("x" * 200) / "track01.m4a"
        long_in_2 = tmp_path / ("y" * 200) / "track01.m4a"
        long_out_1 = tmp_path / ("x" * 200) / "track01.m4a"
        long_out_2 = tmp_path / ("y" * 200) / "track01.m4a"
        for p in (long_in_1, long_in_2):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"data")

        r1 = stage_paths(long_in_1, long_out_1, enabled=True, tmp_root=stage_root)
        r2 = stage_paths(long_in_2, long_out_2, enabled=True, tmp_root=stage_root)

        assert r1.staged_infile != r2.staged_infile, (
            "two distinct long paths must produce distinct staged paths"
        )
        assert r1.staged_outfile != r2.staged_outfile
        # Both staged source files must coexist on disk (no clobber).
        assert r1.staged_infile.exists()
        assert r2.staged_infile.exists()

    def test_only_source_long_stages(self, tmp_path: Path) -> None:
        """If the source is long but the destination is short, staging
        still applies (we never know whether the encoder will internally
        re-resolve the destination)."""
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")
        short_out = tmp_path / "out.m4a"  # short

        r = stage_paths(long_in, short_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is True
        assert r.long_outfile == short_out
        assert r.staged_outfile != short_out  # moved to a short tmp path

    def test_only_destination_long_stages(self, tmp_path: Path) -> None:
        """If the destination is long but the source is short, staging
        still applies."""
        short_in = tmp_path / "in.m4a"
        short_in.write_bytes(b"x")
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_out.parent.mkdir(parents=True, exist_ok=True)

        r = stage_paths(short_in, long_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is True
        assert r.long_outfile == long_out

    def test_source_copy_failure_falls_back_to_long_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """If the source file vanished between scan and convert (or the
        volume is full), the shutil.copy2 inside stage_paths() raises.
        We catch and fall back to the long paths so CoreConverter surfaces
        a clear error instead of us silently using a non-existent staged
        source."""
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        # Note: do NOT create long_in — copy2 will raise FileNotFoundError.
        long_out = tmp_path / ("a" * 200) / "out.m4a"

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False
        assert r.staged_infile == long_in
        assert r.staged_outfile == long_out


# ---------------------------------------------------------------------------
# unstage() copy semantics (literal copy -> unlink)
# ---------------------------------------------------------------------------


class TestUnstage:
    """unstage() copies the staged output to the long destination then
    unlinks both the staged output and the staged source. The flow is a
    literal three-step copy chain (``copy -> convert -> copy``)."""

    def test_successful_copy(self, tmp_path: Path) -> None:
        """A non-empty staged output is copied to the long destination;
        both staged artefacts (source + output) are cleaned up by
        ``unstage()``."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        assert r.staged is True

        # Simulate CoreConverter writing the output to the staged path.
        r.staged_outfile.write_bytes(b"converted audio")

        assert unstage(r) is True
        # Long destination now exists with the converted bytes.
        assert long_out.exists()
        assert long_out.read_bytes() == b"converted audio"
        # Staged source was cleaned up.
        assert not r.staged_infile.exists()
        # Staged output is also cleaned up — unstage unlinks it as
        # final-step housekeeping (we use shutil.copy2, then explicitly
        # unlink; we do NOT rely on move()'s side-effect of consuming
        # the source).
        assert not r.staged_outfile.exists()

    def test_unstage_uses_copy_not_move(self, tmp_path: Path, monkeypatch) -> None:
        """unstage() must use shutil.copy2(), not shutil.move(). The
        staged output MUST remain on disk for the duration of the copy
        so that a mid-copy failure leaves a recoverable artefact. This
        test verifies by spying on shutil.copy2 / shutil.move: the copy
        is called and the move is not."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"converted audio")

        copy_calls: list[tuple[str, str]] = []
        move_calls: list[tuple[str, str]] = []

        import shutil as _shutil  # local import to avoid shadowing

        original_copy2 = _shutil.copy2
        original_move = _shutil.move

        def spy_copy2(src, dst, *args, **kwargs):
            copy_calls.append((str(src), str(dst)))
            return original_copy2(src, dst, *args, **kwargs)

        def spy_move(src, dst, *args, **kwargs):
            move_calls.append((str(src), str(dst)))
            return original_move(src, dst, *args, **kwargs)

        # Patch at the import site used by long_path.py.
        monkeypatch.setattr("src.pathing.long_path.shutil.copy2", spy_copy2)
        monkeypatch.setattr("src.pathing.long_path.shutil.move", spy_move)

        assert unstage(r) is True

        # shutil.copy2 must be called at least once (stage_paths() copies
        # the source, unstage() copies the output). The key call we care
        # about is the staged-out -> long-out one.
        copied_pairs = [c for c in copy_calls if c[0] == str(r.staged_outfile)]
        assert len(copied_pairs) == 1, (
            f"expected exactly one shutil.copy2(staged_outfile, long_outfile), "
            f"got {copy_calls!r}"
        )
        assert copied_pairs[0] == (str(r.staged_outfile), str(r.long_outfile))
        # shutil.move must NEVER have been called inside unstage() — the
        # whole point of switching from move to copy is that the staged
        # file stays alive during the copy.
        assert move_calls == [], (
            f"unstage() must not call shutil.move, got {move_calls!r}"
        )

    def test_staged_source_cleaned_up_even_when_copy_fails(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """If the final copy raises (e.g. full destination volume), the
        staged source and staged output are still cleaned up by the
        finally block — the next run_pipeline.run() should never inherit
        orphaned staged files from a failed job."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"converted audio")

        def failing_copy2(src, dst, *args, **kwargs):
            raise OSError("simulated destination volume full")

        monkeypatch.setattr("src.pathing.long_path.shutil.copy2", failing_copy2)

        assert unstage(r) is False
        # Both staged artefacts should still be cleaned up.
        assert not r.staged_infile.exists(), "staged source leaked after failed copy"
        assert not r.staged_outfile.exists(), "staged output leaked after failed copy"
        # And the long destination should not have been touched.
        assert not long_out.exists()

    def test_missing_staged_output_returns_false(self, tmp_path: Path) -> None:
        """If CoreConverter never wrote anything (or wrote to a different
        path), the staged output is missing and unstage() returns False."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        assert r.staged is True

        # Don't write anything to staged_outfile — simulate CoreConverter
        # never produced output.
        assert unstage(r) is False
        # The long destination must remain untouched.
        assert not long_out.exists()
        # Staged source was cleaned up (we don't want it leaking).
        assert not r.staged_infile.exists()

    def test_empty_staged_output_returns_false(self, tmp_path: Path) -> None:
        """A 0-byte staged output (the qaac-pipe-failure symptom) returns
        False so the caller can report it as a failed conversion."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"")  # 0 bytes — qaac-pipe failure

        assert unstage(r) is False
        # Empty staged output was deleted (unlink-then-fail path).
        assert not r.staged_outfile.exists()
        # Long destination untouched.
        assert not long_out.exists()

    def test_existing_long_destination_is_overwritten(self, tmp_path: Path) -> None:
        """A pre-existing file at the long destination (e.g. from a
        previously-failed attempt) must be overwritten by the fresh
        output. The user explicitly opted into ``--failed-only`` retry
        semantics that depend on this overwrite behaviour."""
        stage_root = tmp_path / "stage"
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_out.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"source")
        long_out.write_bytes(b"OLD STALE OUTPUT")  # leftover from a previous failure

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=stage_root)
        r.staged_outfile.write_bytes(b"new fresh output")

        assert unstage(r) is True
        assert long_out.read_bytes() == b"new fresh output"

    def test_unstage_creates_missing_parent_dir(self, tmp_path: Path) -> None:
        """If the long-destination's parent directory was deleted between
        scan and convert (unusual but possible), unstage() creates it."""
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
# Property aliases
# ---------------------------------------------------------------------------


class TestPropertyAliases:
    """The ``StagingResult.infile`` / ``outfile`` aliases keep the new
    API backwards-compatible with the old 8.3 short-name code path."""

    def test_infile_alias_returns_staged_infile(self, tmp_path: Path) -> None:
        long_in = tmp_path / ("a" * 200) / "in.m4a"
        long_out = tmp_path / ("a" * 200) / "out.m4a"
        long_in.parent.mkdir(parents=True, exist_ok=True)
        long_in.write_bytes(b"x")

        r = stage_paths(long_in, long_out, enabled=True, tmp_root=tmp_path / "stage")
        assert r.infile == r.staged_infile
        assert r.outfile == r.staged_outfile


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


class TestShortHash:
    """The 8-char MD5 prefix is the source-path disambiguator."""

    def test_hash_is_stable(self, tmp_path: Path) -> None:
        h1 = _short_hash(Path("E:/foo/bar/track01.m4a"))
        h2 = _short_hash(Path("E:/foo/bar/track01.m4a"))
        assert h1 == h2

    def test_hash_disambiguates_distinct_paths(self) -> None:
        h1 = _short_hash(Path("E:/foo/track01.m4a"))
        h2 = _short_hash(Path("E:/bar/track01.m4a"))
        assert h1 != h2

    def test_hash_length_is_eight(self) -> None:
        assert len(_short_hash(Path("anything"))) == 8


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
        # Should not raise even when nothing exists.
        cleanup_staging_workspace(tmp_root=tmp_path / "does_not_exist")

    def test_subdirectory_inside_src_is_removed(self, tmp_path: Path) -> None:
        """A leftover directory inside src/ (e.g. from a crashed worker)
        is recursively removed."""
        stage_root = tmp_path / "audio"
        nested = stage_root / "src" / "nested-dir"
        nested.mkdir(parents=True)
        (nested / "file.m4a").write_bytes(b"x")

        cleanup_staging_workspace(tmp_root=stage_root)

        assert not nested.exists()
        assert not (stage_root / "src" / "nested-dir").exists()


# ---------------------------------------------------------------------------
# Cross-platform behaviour
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="win32-only behaviour")
class TestWin32Behavior:
    """On Windows, staging is the default. Short paths must NOT stage."""

    def test_short_paths_skip_staging(self, tmp_path: Path) -> None:
        infile = tmp_path / "short.m4a"
        outfile = tmp_path / "short_out.m4a"
        infile.write_bytes(b"x")

        r = stage_paths(infile, outfile, enabled=True, tmp_root=tmp_path / "stage")
        assert r.staged is False