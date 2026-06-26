"""audio/folder_heuristic.py: Tier 2 — folder-name heuristic for lossy detection.

Scans the parent directory chain looking for known lossy tokens (e.g. "320k",
"mp3", "spotify"). Stops at numeric folders (which are usually album IDs in
sequential scans) and at the filesystem root.
"""

from pathlib import Path
from typing import Optional


# Folder-name tokens that signal a lossy source.  These patterns appear in
# download/release directory names and let us skip the expensive mutagen call
# for tagged releases.
LOSSY_FOLDER_TOKENS: frozenset[str] = frozenset({
    # bitrate + codec variants
    "aac", "mp3", "v0", "v2",
    "128k", "192k", "256k", "320k",
    "128kbps", "192kbps", "256kbps", "320kbps",
    "lame", "l3tag",
    # lossy codec names
    "ogg", "vorbis", "opus", "flac24",
    # streaming / low-quality markers
    "webrip", "shoprip", "itunes", "amazon",
    "deezer", "spotify", "tidal", "qobuz",
    # general lossy umbrella (catch-all last)
    "mp3", "lossy",
})


def _is_lossy_by_folder(path: Path) -> Optional[bool]:
    """Tier 2: return True/False if a lossy token is found in any parent dir, else None.

    Scans from the file's immediate parent up to the filesystem root.
    Stops at the first directory whose name is entirely numeric (e.g. a numeric
    folder like "26005" in a sequential scan) to avoid false positives.
    Also stops when we reach the filesystem root (where parent == self).
    """
    current: Optional[Path] = path.parent
    while current is not None:
        folder_lower = current.name.lower()
        if folder_lower.isdigit():
            break
        for token in LOSSY_FOLDER_TOKENS:
            if token in folder_lower:
                return True
        # Guard against infinite loop at filesystem root (e.g. C:\ on Windows).
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
