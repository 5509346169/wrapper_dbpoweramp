"""sidecars/manager.py: Sidecar file management for lyrics and cover art."""

import shutil
from pathlib import Path

from models.types import CoverPolicy, SidecarPolicy

from pathing.resolver import hide_filename


def copy_lyrics(
    infile: Path,
    outfile: Path,
    policy: SidecarPolicy | None,
) -> list[Path]:
    """
    Copy lyric/text sidecar files next to the output file.

    For each extension in policy.extensions, looks for infile.with_suffix(ext)
    (a lyric file with the same stem next to the audio file) and copies it
    to outfile.with_suffix(ext).

    Args:
        infile: The source audio file path.
        outfile: The destination audio file path.
        policy: The sidecar policy specifying what to copy.

    Returns:
        List of Path objects for files that were written.
        Returns [] if policy is None or policy.copy is False.
    """
    if policy is None or not policy.copy:
        return []

    written: list[Path] = []
    for ext in policy.extensions:
        lyric_src = infile.with_suffix(ext)
        if lyric_src.exists():
            lyric_dst = outfile.with_suffix(ext)
            if not lyric_dst.exists():
                shutil.copy2(lyric_src, lyric_dst)
                written.append(lyric_dst)
    return written


def copy_covers(
    infile: Path,
    outfile: Path,
    policy: CoverPolicy | None,
) -> list[Path]:
    """
    Copy cover art files to the output directory.

    Looks for policy.patterns (exact filenames like 'cover.jpg', 'cover.png')
    in infile.parent. For each match, copies to outfile.parent, applying
    hide_filename() if policy.hide is True.

    Skips if destination already exists (idempotent).

    Args:
        infile: The source audio file path.
        outfile: The destination audio file path.
        policy: The cover policy specifying what patterns to look for and how to name them.

    Returns:
        List of Path objects for files that were written.
        Returns [] if policy is None or policy.copy is False.
    """
    if policy is None or not policy.copy:
        return []

    written: list[Path] = []
    for pattern in policy.patterns:
        cover_src = infile.parent / pattern
        if cover_src.exists():
            dest_name = hide_filename(pattern) if policy.hide else pattern
            cover_dst = outfile.parent / dest_name
            if not cover_dst.exists():
                shutil.copy2(cover_src, cover_dst)
                written.append(cover_dst)
    return written
