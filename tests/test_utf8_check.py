"""tests/test_utf8_check.py: Tests for name_needs_staging() trigger logic."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestNameNeedsStaging:
    """Test cases for the UTF-8 / MAX_PATH trigger."""

    def test_ascii_short_returns_false(self, tmp_path: Path) -> None:
        """ASCII-only filename under 240 chars does not need staging."""
        from src.pathing.utf8_check import name_needs_staging

        p = tmp_path / "music" / "album" / "track01.flac"
        assert not name_needs_staging(p)

    def test_non_ascii_in_filename_returns_true(self, tmp_path: Path) -> None:
        """Non-ASCII characters in the filename trigger staging."""
        from src.pathing.utf8_check import name_needs_staging

        # Japanese filename
        p = tmp_path / "音楽" / "track01.flac"
        assert name_needs_staging(p)

    def test_non_ascii_in_parent_returns_true(self, tmp_path: Path) -> None:
        """Non-ASCII characters in any parent directory trigger staging."""
        from src.pathing.utf8_check import name_needs_staging

        # Use a real non-ASCII folder name (JP artist folder)
        p = tmp_path / "AM-DL" / "日本語" / "GUMI [406470856]" / "track.flac"
        assert name_needs_staging(p)

    def test_accents_in_filename_returns_true(self, tmp_path: Path) -> None:
        """Accented Latin characters trigger staging."""
        from src.pathing.utf8_check import name_needs_staging

        p = tmp_path / "Café" / "macchiato.mp3"
        assert name_needs_staging(p)

    def test_cyrillic_returns_true(self, tmp_path: Path) -> None:
        """Cyrillic characters trigger staging."""
        from src.pathing.utf8_check import name_needs_staging

        p = tmp_path / "Музыка" / "track.flac"
        assert name_needs_staging(p)

    def test_emoji_in_path_returns_true(self, tmp_path: Path) -> None:
        """Emoji in any path component triggers staging."""
        from src.pathing.utf8_check import name_needs_staging

        p = tmp_path / "🎵 Music" / "song.flac"
        assert name_needs_staging(p)

    def test_long_path_only_returns_true(self, tmp_path: Path) -> None:
        """Path exceeding 240 chars triggers staging even with all-ASCII."""
        from src.pathing.utf8_check import name_needs_staging

        # Build a path > 240 chars with only ASCII chars
        parts = ["folder_" + str(i) for i in range(30)]
        long_path = tmp_path.joinpath(*parts) / "track.flac"
        assert len(str(long_path)) > 240, "Test path must exceed 240 chars"
        assert name_needs_staging(long_path)

    def test_long_ascii_path_returns_true(self, tmp_path: Path) -> None:
        """ASCII path > 240 chars needs staging even without UTF-8."""
        from src.pathing.utf8_check import name_needs_staging

        # 30-char folder names × 10 = 300 chars + filename
        long_path = tmp_path
        for i in range(10):
            long_path = long_path / ("x" * 30)
        long_path = long_path / "track.flac"
        assert len(str(long_path)) > 240
        assert name_needs_staging(long_path)

    def test_very_short_ascii_returns_false(self, tmp_path: Path) -> None:
        """Very short ASCII path needs no staging."""
        from src.pathing.utf8_check import name_needs_staging

        p = tmp_path / "a.flac"
        assert len(str(p)) <= 240
        assert not name_needs_staging(p)


class TestPathIsLong:
    """Test _path_is_long threshold."""

    def test_under_threshold_returns_false(self, tmp_path: Path) -> None:
        """Path <= 240 chars is not considered long."""
        from src.pathing.utf8_check import _path_is_long

        p = tmp_path / "music" / "album.flac"
        assert not _path_is_long(p)

    def test_over_threshold_returns_true(self, tmp_path: Path) -> None:
        """Path > 240 chars is considered long."""
        from src.pathing.utf8_check import _path_is_long

        # 30-char folder × 10 = 300 + base
        long_path = tmp_path
        for i in range(10):
            long_path = long_path / ("x" * 30)
        long_path = long_path / "track.flac"
        assert len(str(long_path)) > 240
        assert _path_is_long(long_path)

    def test_exactly_240_returns_false(self) -> None:
        """Path exactly 240 chars is not considered long."""
        from src.pathing.utf8_check import _path_is_long

        # Windows Path normalises / to \, adding 1 char to the str length.
        # So we need base_length + x_count + "/a.flac" = 240.
        # "C:/x/" → 5 chars; "/a.flac" → 7 chars; x_count = 240 - 5 - 7 = 228.
        base = "C:/x/"
        x_count = 240 - len(base) - len("/a.flac")
        p = Path(base + "x" * x_count + "/a.flac")
        assert len(str(p)) == 240, f"expected 240, got {len(str(p))}: {str(p)!r}"
        assert not _path_is_long(p)

    def test_241_returns_true(self) -> None:
        """Path of 241 chars is considered long."""
        from src.pathing.utf8_check import _path_is_long

        # Same logic: x_count = 241 - 5 - 7 = 229.
        base = "C:/x/"
        x_count = 241 - len(base) - len("/a.flac")
        p = Path(base + "x" * x_count + "/a.flac")
        assert len(str(p)) == 241, f"expected 241, got {len(str(p))}: {str(p)!r}"
        assert _path_is_long(p)
