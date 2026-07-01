"""index/playlist.py: Parser for .m3u / .m3u8 / .pls playlist files.

Playlist entries are returned as resolved absolute Path objects. Relative paths
are resolved against the playlist file's parent directory so that playlists
referencing files by relative paths (e.g. "Music/Track01.flac") work regardless
of the current working directory.

Supported formats:
  - Extended M3U  (.m3u / .m3u8): lines starting with ``#EXTINF`` are metadata;
    all other non-blank, non-comment lines are entry paths.
  - Basic M3U     (.m3u / .m3u8): every non-blank, non-comment line is an entry path.
  - PLS           (.pls): ``FileN=<filepath>`` key-value pairs inside a ``[playlist]`` section.

Empty lines and lines that start with ``#`` (M3U comments / PLS comments) are ignored.
Lines that fail to resolve to an existing file are silently skipped (the playlist
may contain conditional entries, platform-specific paths, etc.).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

# Extensions considered audio (used to filter out non-audio playlist entries).
AUDIO_EXTENSIONS: set[str] = {
    ".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav",
    ".ape", ".wv", ".tta", ".aiff", ".aif", ".wma", ".ogg",
}


def _resolve_entry(raw_path: str, playlist_path: Path) -> Path | None:
    """Resolve a raw playlist path to an absolute Path.

    Relative paths are anchored to the playlist file's parent directory.
    Absolute paths are resolved as-is.

    Returns None if the resolved path does not exist or is not a file.
    """
    raw = raw_path.strip()
    if not raw:
        return None

    # Strip surrounding quotes that some exporters wrap around paths.
    if len(raw) >= 2 and ((raw[0] == '"' and raw[-1] == '"') or (raw[0] == "'" and raw[-1] == "'")):
        raw = raw[1:-1].strip()

    # Treat an absolute path as-is; resolve a relative path from the playlist's dir.
    if Path(raw).is_absolute():
        candidate = Path(raw)
    else:
        candidate = (playlist_path.parent / raw).resolve()

    return candidate if candidate.is_file() else None


def parse_m3u(playlist_path: Path) -> Iterator[Path]:
    """Parse an M3U / M3U8 playlist file and yield resolved audio file paths.

    ``#EXTINF`` lines are treated as metadata and ignored. All other non-blank,
    non-comment lines are treated as entry paths and resolved against the
    playlist's parent directory.

    Args:
        playlist_path: Path to the .m3u / .m3u8 file.

    Yields:
        Absolute Path objects for audio files that exist on disk.
    """
    with open(playlist_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.rstrip("\n\r")
            if not stripped or stripped.startswith("#"):
                continue
            resolved = _resolve_entry(stripped, playlist_path)
            if resolved is not None:
                yield resolved


def parse_pls(playlist_path: Path) -> Iterator[Path]:
    """Parse a PLS playlist file and yield resolved audio file paths.

    PLS files use a key-value format with ``FileN=<filepath>`` entries inside
    a ``[playlist]`` section. Entries outside the section are ignored.

    Args:
        playlist_path: Path to the .pls file.

    Yields:
        Absolute Path objects for audio files that exist on disk.
    """
    # Regex matches "File1=<filepath>", "File2=C:\\path\\to\\track.flac", etc.
    entry_re = re.compile(r"^File\d+=(?P<path>.+)$", re.IGNORECASE)

    in_playlist_section = False
    with open(playlist_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            lower = stripped.lower()
            if lower == "[playlist]":
                in_playlist_section = True
                continue
            # A new section header ends the playlist section.
            if re.match(r"^\[.+\]$", lower):
                in_playlist_section = False
                continue
            if not in_playlist_section:
                continue
            match = entry_re.match(stripped)
            if not match:
                continue
            resolved = _resolve_entry(match.group("path"), playlist_path)
            if resolved is not None:
                yield resolved


def parse_playlist(playlist_path: Path) -> list[Path]:
    """Parse any supported playlist format and return resolved audio file paths.

    The format is auto-detected from the file extension.

    Args:
        playlist_path: Path to the playlist file.

    Returns:
        A list of absolute Path objects for audio files that exist on disk,
        in the order they appear in the playlist.

    Raises:
        ValueError: If the file extension is not a supported playlist format.
    """
    ext = playlist_path.suffix.lower()
    if ext in (".m3u", ".m3u8"):
        return list(parse_m3u(playlist_path))
    elif ext == ".pls":
        return list(parse_pls(playlist_path))
    else:
        raise ValueError(
            f"Unsupported playlist format: {ext!r} "
            f"(supported: .m3u, .m3u8, .pls)"
        )
