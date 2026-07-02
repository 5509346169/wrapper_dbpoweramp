"""pathing/utf8_check.py: UTF-8 / MAX_PATH trigger for md5sum temp staging.

Determines whether a source or destination path needs to go through the
md5sum-named staging layer to avoid qaac / CoreConverter UTF-8 handling
failures and Windows MAX_PATH truncation.

A path needs staging when:
  1. Any component of the path contains non-ASCII characters
     (qaac/CoreConverter can't reliably open these as-is).
  2. OR the absolute path string exceeds 240 characters (the safety
     threshold below MAX_PATH=260, leaving headroom for the command-line
     quoting wrapper).

This module is pure and has no I/O dependencies — safe to call from any
context.
"""

from __future__ import annotations

from pathlib import Path


def _path_is_long(path: Path) -> bool:
    """Return True iff the absolute form of *path* exceeds the safety threshold.

    We use 240 instead of 260 (the legacy MAX_PATH limit) because the
    path appears inside ``-outfile="..."`` on the command line, turning a
    260-char path on disk into a ~280-char token after double-quoting.
    Staging anything past this threshold guarantees CoreConverter never
    sees a path that could push into MAX_PATH territory.
    """
    return len(str(path)) > 240  # _MAX_PATH_SAFE from long_path.py


def name_needs_staging(path: Path) -> bool:
    """Return True if *path* needs md5sum temp staging.

    Checks two independent conditions:
      1. Non-ASCII in the path (filename or any parent directory).
         Detected by attempting ``encode('ascii', 'strict')`` on each
         component — raises ``UnicodeEncodeError`` if any character is
         non-ASCII.  This catches CJK, Cyrillic, accented Latin, emoji,
         and any other non-ASCII glyph that qaac/CoreConverter mishandles.
      2. Total path length > 240 chars (MAX_PATH safety threshold).

    Either condition alone is sufficient to trigger staging.

    Args:
        path: The source or destination path to evaluate.

    Returns:
        True if staging is recommended, False otherwise.
    """
    # Check 1: non-ASCII characters in any path component.
    try:
        for part in path.parts:
            part.encode("ascii", "strict")
    except UnicodeEncodeError:
        return True

    # Check 2: total path length exceeds the MAX_PATH safety threshold.
    if _path_is_long(path):
        return True

    return False


__all__ = ["name_needs_staging", "_path_is_long"]
