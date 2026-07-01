"""tests/test_playlist.py: Tests for the playlist parser."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.index.playlist import parse_m3u, parse_pls, parse_playlist


# ── Helpers ─────────────────────────────────────────────────────────────────

def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ── M3U tests ────────────────────────────────────────────────────────────────

class TestParseM3U:
    def test_absolute_paths(self, tmp_path: Path):
        """Absolute paths in the playlist are returned as-is (resolved)."""
        (tmp_path / "a.flac").touch()
        (tmp_path / "b.mp3").touch()
        pl = tmp_path / "list.m3u"
        pl.write_text(str(tmp_path / "a.flac") + "\n" + str(tmp_path / "b.mp3") + "\n")
        result = list(parse_m3u(pl))
        assert result == [tmp_path / "a.flac", tmp_path / "b.mp3"]

    def test_relative_paths_resolved_from_playlist_dir(self, tmp_path: Path):
        """Relative paths are anchored to the playlist's parent directory."""
        sub = tmp_path / "Music"
        sub.mkdir()
        (sub / "Track01.flac").touch()
        (sub / "Track02.mp3").touch()

        pl = sub.parent / "playlist.m3u"
        pl.write_text("Music/Track01.flac\nMusic/Track02.mp3\n")

        result = list(parse_m3u(pl))
        assert result == [sub / "Track01.flac", sub / "Track02.mp3"]

    def test_extinf_lines_are_skipped(self, tmp_path: Path):
        """#EXTINF lines are treated as metadata and ignored."""
        (tmp_path / "song.flac").touch()
        pl = tmp_path / "playlist.m3u"
        pl.write_text("#EXTINF:123,Artist Name\nsong.flac\n#EXTINF:456,Another Artist\nsong.flac\n")

        result = list(parse_m3u(pl))
        # Both song.flac entries are returned (EXTINF is metadata only).
        assert result == [tmp_path / "song.flac", tmp_path / "song.flac"]

    def test_comments_and_blank_lines_ignored(self, tmp_path: Path):
        """Blank lines and lines starting with # (not EXTINF) are skipped."""
        (tmp_path / "a.flac").touch()
        pl = tmp_path / "playlist.m3u"
        pl.write_text("# my comment\na.flac\n\n  \n#EXTINF:10,title\na.flac\n")

        result = list(parse_m3u(pl))
        # Both a.flac entries are returned (# comment and #EXTINF are both skipped).
        assert result == [tmp_path / "a.flac", tmp_path / "a.flac"]

    def test_missing_files_omitted(self, tmp_path: Path):
        """Entries that resolve to non-existent files are silently skipped."""
        pl = tmp_path / "playlist.m3u"
        pl.write_text("existing.flac\nnonexistent.flac\n")

        (tmp_path / "existing.flac").touch()

        result = list(parse_m3u(pl))
        assert result == [tmp_path / "existing.flac"]

    def test_quoted_paths_stripped(self, tmp_path: Path):
        """Paths surrounded by single or double quotes are unquoted before resolution."""
        (tmp_path / "song.flac").touch()
        pl = tmp_path / "playlist.m3u"
        pl.write_text('"song.flac"\n\'song.flac\'\n')

        result = list(parse_m3u(pl))
        assert result == [tmp_path / "song.flac", tmp_path / "song.flac"]

    def test_m3u8_extension(self, tmp_path: Path):
        """parse_m3u is used for both .m3u and .m3u8 files."""
        (tmp_path / "song.flac").touch()
        pl = tmp_path / "playlist.m3u8"
        pl.write_text("song.flac\n")
        result = list(parse_m3u(pl))
        assert result == [tmp_path / "song.flac"]


# ── PLS tests ────────────────────────────────────────────────────────────────

class TestParsePls:
    def test_basic_playlist(self, tmp_path: Path):
        """Basic PLS format entries are returned in order."""
        (tmp_path / "a.flac").touch()
        (tmp_path / "b.mp3").touch()
        pl = tmp_path / "playlist.pls"
        pl.write_text("[playlist]\nFile1=a.flac\nFile2=b.mp3\nNumberOfEntries=2\n")

        result = list(parse_pls(pl))
        assert result == [tmp_path / "a.flac", tmp_path / "b.mp3"]

    def test_missing_entries_omitted(self, tmp_path: Path):
        """PLS entries that resolve to non-existent files are silently skipped."""
        (tmp_path / "exists.flac").touch()
        pl = tmp_path / "playlist.pls"
        pl.write_text("[playlist]\nFile1=exists.flac\nFile2=missing.flac\n")

        result = list(parse_pls(pl))
        assert result == [tmp_path / "exists.flac"]

    def test_entries_outside_playlist_section_ignored(self, tmp_path: Path):
        """Entries outside the [playlist] section are skipped."""
        (tmp_path / "x.flac").touch()
        pl = tmp_path / "playlist.pls"
        pl.write_text("[playlist]\nFile1=x.flac\n[other_section]\nFile2=x.flac\n")

        result = list(parse_pls(pl))
        assert result == [tmp_path / "x.flac"]

    def test_relative_paths_from_playlist_dir(self, tmp_path: Path):
        """Relative paths in PLS entries are anchored to the playlist's parent directory."""
        (tmp_path / "song.flac").touch()
        pl = tmp_path / "playlist.pls"
        pl.write_text("[playlist]\nFile1=song.flac\n")

        result = list(parse_pls(pl))
        assert result == [tmp_path / "song.flac"]

    def test_empty_pls(self, tmp_path: Path):
        """An empty PLS file yields an empty list."""
        pl = tmp_path / "empty.pls"
        pl.write_text("[playlist]\n")
        assert list(parse_pls(pl)) == []


# ── parse_playlist auto-detection ────────────────────────────────────────────

class TestParsePlaylist:
    def test_m3u_routes_to_parse_m3u(self, tmp_path: Path):
        """parse_playlist dispatches .m3u to parse_m3u."""
        (tmp_path / "a.flac").touch()
        pl = tmp_path / "list.m3u"
        pl.write_text("a.flac\n")
        assert parse_playlist(pl) == [tmp_path / "a.flac"]

    def test_m3u8_routes_to_parse_m3u(self, tmp_path: Path):
        """parse_playlist dispatches .m3u8 to parse_m3u."""
        (tmp_path / "a.flac").touch()
        pl = tmp_path / "list.m3u8"
        pl.write_text("a.flac\n")
        assert parse_playlist(pl) == [tmp_path / "a.flac"]

    def test_pls_routes_to_parse_pls(self, tmp_path: Path):
        """parse_playlist dispatches .pls to parse_pls."""
        (tmp_path / "a.flac").touch()
        pl = tmp_path / "list.pls"
        pl.write_text("[playlist]\nFile1=a.flac\n")
        assert parse_playlist(pl) == [tmp_path / "a.flac"]

    def test_unsupported_extension_raises(self, tmp_path: Path):
        """An unsupported file extension raises ValueError."""
        pl = tmp_path / "list.txt"
        pl.write_text("a.flac\n")
        with pytest.raises(ValueError, match="Unsupported playlist format"):
            parse_playlist(pl)

    def test_order_preserved(self, tmp_path: Path):
        """Entries are returned in the same order they appear in the playlist."""
        for i in range(5):
            (tmp_path / f"track{i}.flac").touch()
        pl = tmp_path / "order.m3u"
        pl.write_text("\n".join(f"track{i}.flac" for i in range(5)) + "\n")
        assert parse_playlist(pl) == [tmp_path / f"track{i}.flac" for i in range(5)]
