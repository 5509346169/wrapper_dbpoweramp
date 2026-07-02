"""tests/test_md5_staging.py: Tests for md5_staging module — compute_md5sum, stage_paths_v2, unstage_v2."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


class TestComputeMd5sum:
    """Tests for the deterministic MD5 computation."""

    def test_deterministic(self, tmp_path: Path) -> None:
        """Same path always produces the same hash."""
        from src.pathing.md5_staging import compute_md5sum

        p = tmp_path / "music" / "track.flac"
        h1 = compute_md5sum(p)
        h2 = compute_md5sum(p)
        assert h1 == h2

    def test_different_paths_different_hash(self, tmp_path: Path) -> None:
        """Different paths produce different hashes."""
        from src.pathing.md5_staging import compute_md5sum

        p1 = tmp_path / "music" / "a.flac"
        p2 = tmp_path / "music" / "b.flac"
        assert compute_md5sum(p1) != compute_md5sum(p2)

    def test_12_chars(self, tmp_path: Path) -> None:
        """Hash is exactly 12 characters."""
        from src.pathing.md5_staging import compute_md5sum

        p = tmp_path / "track.flac"
        h = compute_md5sum(p)
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_utf8_path(self, tmp_path: Path) -> None:
        """UTF-8 path is hashed correctly (non-ASCII characters)."""
        from src.pathing.md5_staging import compute_md5sum

        p = tmp_path / "日本語" / "track.flac"
        h = compute_md5sum(p)
        assert len(h) == 12


class TestStagePathsV2:
    """Tests for stage_paths_v2."""

    def test_disabled_returns_staged_false(self, tmp_path: Path) -> None:
        """When enabled=False, no staging is applied."""
        from src.pathing.md5_staging import stage_paths_v2

        src = tmp_path / "src.flac"
        dst = tmp_path / "dst.flac"
        src.touch()
        result = stage_paths_v2(src, dst, enabled=False)
        assert not result.staged
        assert result.staged_infile == src
        assert result.staged_outfile == dst

    def test_non_win32_returns_staged_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """On non-Windows platforms, no staging is applied."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "linux")
        src = tmp_path / "src.flac"
        dst = tmp_path / "dst.flac"
        src.touch()
        result = stage_paths_v2(src, dst, enabled=True)
        assert not result.staged

    def test_ascii_short_returns_staged_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ASCII-only short path on Windows with auto mode returns staged=False."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "src.flac"
        dst = tmp_path / "dst.flac"
        src.touch()
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="auto")
        assert not result.staged

    def test_utf8_name_returns_staged_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-ASCII filename triggers staging."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="auto")
        assert result.staged
        assert ".md5hash." in result.temp_filename
        assert result.temp_filename.endswith(".md5hash.flac")

    def test_md5sum_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Staged filename uses <12-hex-md5>.md5hash.<ext> format."""
        from src.pathing.md5_staging import compute_md5sum, stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"
        expected_md5 = compute_md5sum(src)
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="auto")
        assert result.staged
        assert result.temp_filename == f"{expected_md5}.md5hash.flac"

    def test_md5sum_in_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Result.md5sum is always populated regardless of staged."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "a.flac"
        src.touch()
        dst = tmp_path / "b.flac"
        result = stage_paths_v2(src, dst, enabled=False)
        assert result.md5sum != ""

    def test_long_path_triggers_staging(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Path > 240 chars triggers staging even with all-ASCII."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        long_path = tmp_path
        for i in range(10):
            long_path = long_path / ("x" * 30)
        long_path = long_path / "track.flac"
        long_path.parent.mkdir(parents=True, exist_ok=True)
        long_path.touch()
        assert len(str(long_path)) > 240
        src = long_path
        dst = tmp_path / "output.flac"
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="auto")
        assert result.staged

    def test_md5_staging_off_uses_legacy_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """md5_staging='off' uses the legacy <8-hex>__<basename> form."""
        from src.pathing.md5_staging import compute_md5sum, stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"
        expected_md5 = compute_md5sum(src)
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="off")
        assert result.staged
        assert result.temp_filename == f"{expected_md5[:8]}__output.flac"
        assert ".md5hash." not in result.temp_filename

    def test_copy_failure_returns_staged_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the source file copy fails, staged=False is returned."""
        from src.pathing.md5_staging import stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "nonexistent.flac"
        dst = tmp_path / "output.flac"
        result = stage_paths_v2(src, dst, enabled=True, md5_staging="auto")
        assert not result.staged

    def test_collision_random_suffix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the md5hash name already exists, a random suffix is appended."""
        from src.pathing.md5_staging import compute_md5sum, stage_paths_v2

        monkeypatch.setattr(sys, "platform", "win32")
        src = tmp_path / "日本語.flac"
        src.touch()
        dst = tmp_path / "output.flac"
        tmp_root = tmp_path / "staging"
        tmp_root.mkdir()
        expected_md5 = compute_md5sum(src)
        # Pre-create the staging file
        (tmp_root / "src").mkdir()
        (tmp_root / "src" / f"{expected_md5}.md5hash.flac").touch()
        result = stage_paths_v2(src, dst, enabled=True, tmp_root=tmp_root, md5_staging="auto")
        assert result.staged
        # The collision recovery should have appended a suffix
        assert result.temp_filename.startswith(f"{expected_md5}-")
        assert ".md5hash." in result.temp_filename


class TestUnstageV2:
    """Tests for unstage_v2."""

    def test_not_staged_verifies_output_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When staged=False, verify the original output exists and is non-empty."""
        from src.pathing.md5_staging import StagingResult, unstage_v2

        monkeypatch.setattr(sys, "platform", "win32")
        out = tmp_path / "output.flac"
        out.write_bytes(b"converted audio data")
        result = StagingResult(
            long_infile=tmp_path / "src.flac",
            long_outfile=out,
            staged_infile=out,
            staged_outfile=out,
            staged=False,
            md5sum="abcd12345678",
            temp_filename="",
        )
        assert unstage_v2(result)

    def test_not_staged_missing_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When staged=False and output is missing, returns False."""
        from src.pathing.md5_staging import StagingResult, unstage_v2

        monkeypatch.setattr(sys, "platform", "win32")
        out = tmp_path / "nonexistent.flac"
        result = StagingResult(
            long_infile=tmp_path / "src.flac",
            long_outfile=out,
            staged_infile=out,
            staged_outfile=out,
            staged=False,
            md5sum="abcd12345678",
            temp_filename="",
        )
        assert not unstage_v2(result)

    def test_staged_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful transfer: destination exists, staged gone, returns True."""
        from src.pathing.md5_staging import StagingResult, unstage_v2

        monkeypatch.setattr(sys, "platform", "win32")
        tmp_root = tmp_path / "staging"
        (tmp_root / "src").mkdir(parents=True)
        (tmp_root / "dst").mkdir(parents=True)

        staged_out = tmp_root / "dst" / "abc123456789.md5hash.flac"
        staged_out.write_bytes(b"converted audio")
        long_out = tmp_path / "long_output.flac"

        result = StagingResult(
            long_infile=tmp_path / "src.flac",
            long_outfile=long_out,
            staged_infile=tmp_root / "src" / "abc123456789.md5hash.flac",
            staged_outfile=staged_out,
            staged=True,
            md5sum="abc123456789",
            temp_filename="abc123456789.md5hash.flac",
        )
        assert unstage_v2(result)
        assert long_out.exists()
        assert long_out.read_bytes() == b"converted audio"
        assert not staged_out.exists()

    def test_staged_empty_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """0-byte staged output returns False and cleans up."""
        from src.pathing.md5_staging import StagingResult, unstage_v2

        monkeypatch.setattr(sys, "platform", "win32")
        tmp_root = tmp_path / "staging"
        (tmp_root / "src").mkdir(parents=True)
        (tmp_root / "dst").mkdir(parents=True)

        staged_out = tmp_root / "dst" / "abc123456789.md5hash.flac"
        staged_out.write_bytes(b"")  # 0-byte file
        long_out = tmp_path / "long_output.flac"

        result = StagingResult(
            long_infile=tmp_path / "src.flac",
            long_outfile=long_out,
            staged_infile=tmp_root / "src" / "abc.md5hash.flac",
            staged_outfile=staged_out,
            staged=True,
            md5sum="abc123456789",
            temp_filename="abc123456789.md5hash.flac",
        )
        assert not unstage_v2(result)
        assert not long_out.exists()
        assert not staged_out.exists()

    def test_staged_missing_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing staged output returns False."""
        from src.pathing.md5_staging import StagingResult, unstage_v2

        monkeypatch.setattr(sys, "platform", "win32")
        long_out = tmp_path / "long_output.flac"

        result = StagingResult(
            long_infile=tmp_path / "src.flac",
            long_outfile=long_out,
            staged_infile=tmp_path / "missing_src",
            staged_outfile=tmp_path / "missing_dst",
            staged=True,
            md5sum="abc123456789",
            temp_filename="abc123456789.md5hash.flac",
        )
        assert not unstage_v2(result)


class TestStagingResultFields:
    """Tests that StagingResult always carries md5sum."""

    def test_md5sum_populated_when_not_staged(self, tmp_path: Path) -> None:
        """md5sum is always available, even when staged=False."""
        from src.pathing.md5_staging import StagingResult

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

    def test_temp_filename_populated_when_staged(self, tmp_path: Path) -> None:
        """temp_filename is populated when staged=True."""
        from src.pathing.md5_staging import StagingResult

        r = StagingResult(
            long_infile=tmp_path / "a.flac",
            long_outfile=tmp_path / "b.flac",
            staged_infile=tmp_path / "staged_a.flac",
            staged_outfile=tmp_path / "staged_b.flac",
            staged=True,
            md5sum="abcd123456ef",
            temp_filename="abcd123456ef.md5hash.flac",
        )
        assert r.temp_filename == "abcd123456ef.md5hash.flac"

    def test_infole_outfile_alias(self, tmp_path: Path) -> None:
        """infile/outfile aliases work for backward compat."""
        from src.pathing.md5_staging import StagingResult

        r = StagingResult(
            long_infile=tmp_path / "a.flac",
            long_outfile=tmp_path / "b.flac",
            staged_infile=tmp_path / "staged_a.flac",
            staged_outfile=tmp_path / "staged_b.flac",
            staged=True,
        )
        assert r.infile == tmp_path / "staged_a.flac"
        assert r.outfile == tmp_path / "staged_b.flac"
