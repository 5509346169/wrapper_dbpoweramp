"""index/scanner.py: File-tree scanner with optional progress bar for the temp index snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import Optional

from src.models.types import AUDIO_EXTENSIONS
from src.ui.progress_view import ProgressSink


@dataclass(frozen=False, slots=True)
class IndexRow:
    """A row in the temp index snapshot. ``dest_path`` and ``job_type`` are filled by the job builder."""

    source_path: str
    dest_path: str
    job_type: str
    file_size: int
    sidecar_files: str
    mtime: float
    is_lossy: Optional[bool] = None


def _discover_audio_files(input_path: Path, excludes: list[str]) -> list[Path]:
    """Return sorted list of audio files under input_path.

    Mirrors the public ``discover_audio_files`` in ``jobs/builder.py:13-37``.
    """
    if input_path.is_file():
        return [input_path]

    exclude_set = set(excludes)
    audio_files: list[Path] = []

    for item in input_path.rglob("*"):
        if item.is_dir():
            continue
        if item.suffix.lower() in AUDIO_EXTENSIONS:
            if item.parent.name not in exclude_set:
                audio_files.append(item)

    return sorted(audio_files)


def _collect_sidecar_basenames(
    infile: Path,
    lyrics_policy,
    covers_policy,
) -> str:
    """Return newline-joined basenames of all existing sidecar files for ``infile``."""
    names: list[str] = []

    if lyrics_policy is not None and getattr(lyrics_policy, "copy", False):
        for ext in getattr(lyrics_policy, "extensions", []):
            sibling = infile.with_suffix(ext)
            if sibling.exists():
                names.append(sibling.name)

    if covers_policy is not None and getattr(covers_policy, "copy", False):
        for pattern in getattr(covers_policy, "patterns", []):
            sibling = infile.parent / pattern
            if sibling.exists():
                names.append(sibling.name)

    return "\n".join(names)


def scan_with_progress(
    input_path: Path,
    excludes: list[str],
    preset,
    progress: ProgressSink,
) -> tuple[list[IndexRow], dict[Path, str]]:
    """Walk ``input_path`` once, collecting file stats and sidecar candidates.

    Returns partial ``IndexRow`` objects (with empty ``dest_path`` and ``job_type`` —
    the caller fills those in after lossy classification) plus a dict mapping each
    source ``Path`` to its newline-joined sidecar basenames.

    Args:
        input_path: File or directory to scan.
        excludes: Directory basenames to skip during the walk.
        preset: ``PresetConfig`` — used to determine which sidecar patterns to look for.
        progress: ``ProgressSink`` for live reporting.

    Returns:
        ``(rows, sidecar_map)`` where ``rows`` is a list of ``IndexRow`` and
        ``sidecar_map`` is a ``dict[Path, str]`` from source path to sidecar basenames.
    """
    audio_files = _discover_audio_files(input_path, excludes)
    total = len(audio_files)
    progress.log(f"Scanning {total} file(s)...")
    rows: list[IndexRow] = []
    sidecar_map: dict[Path, str] = {}

    lyrics_policy = getattr(preset, "lyrics", None) if preset is not None else None
    covers_policy = getattr(preset, "covers", None) if preset is not None else None

    for infile in audio_files:
        stat = infile.stat()
        sidecar_basenames = _collect_sidecar_basenames(infile, lyrics_policy, covers_policy)
        sidecar_map[infile] = sidecar_basenames
        rows.append(
            IndexRow(
                source_path=str(infile),
                dest_path="",
                job_type="",
                file_size=stat.st_size,
                sidecar_files=sidecar_basenames,
                mtime=stat.st_mtime,
            )
        )
        progress.advance()

    return rows, sidecar_map
