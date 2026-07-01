"""index/scanner.py: File-tree scanner with optional progress bar for the temp index snapshot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING, Optional

from src.models.types import AUDIO_EXTENSIONS
from src.ui.progress_view import ProgressSink

if TYPE_CHECKING:
    from src.index.scan_cache import ScanCache

# Re-exported for callers that build IndexRow objects directly.
ScannedFile = tuple[Path, int, float, str]


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


def _discover_audio_files(
    input_path: Path, excludes: list[str]
) -> list[tuple[Path, int, float]]:
    """Walk ``input_path`` with ``os.scandir`` and return audio file metadata.

    Returns a list of ``(path, size, mtime)`` tuples so callers don't need to
    re-stat each file. ``os.scandir`` is significantly faster than
    ``Path.rglob`` on Windows because the underlying ``FindNextFileW`` call
    returns directory entries with cached file attributes in a single syscall
    per entry (size, mtime, is_dir, etc.). ``Path.rglob`` walks the tree and
    then performs a separate ``stat()`` for each path to determine whether it's
    a directory, doubling the syscall count.

    Excludes are matched against directory basenames (the directory is
    skipped before recursion). The output is sorted by path for deterministic
    ordering across runs.
    """
    if input_path.is_file():
        try:
            st = input_path.stat()
        except OSError:
            return []
        return [(input_path, st.st_size, st.st_mtime)]

    exclude_set = set(excludes)
    # AUDIO_EXTENSIONS is already lowercase; preserve it as a tuple for fast
    # str.endswith(tuple) checks in the walker.
    audio_suffixes: tuple[str, ...] = tuple(AUDIO_EXTENSIONS)
    results: list[tuple[Path, int, float]] = []

    # Iterative DFS using a stack. We avoid Path.rglob because it stats each
    # yielded entry twice (once to enumerate, once via is_dir).
    stack: list[str] = [str(input_path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    name = entry.name
                    # Fast path: directories first — entry.is_dir() uses cached
                    # attributes from FindNextFileW on Windows.
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if is_dir:
                        if name in exclude_set:
                            continue
                        stack.append(entry.path)
                        continue
                    # Files: filter by extension using the C-level endswith.
                    if not name.lower().endswith(audio_suffixes):
                        continue
                    # Cached stat from the same DirEntry handle — no extra syscall.
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    results.append((Path(entry.path), st.st_size, st.st_mtime))
        except (PermissionError, FileNotFoundError, OSError):
            # Skip directories we can't read rather than aborting the whole scan.
            continue

    results.sort(key=lambda item: str(item[0]))
    return results


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
    audio_files: list[tuple[Path, int, float]] | None = None,
    cache: "ScanCache | None" = None,
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
        audio_files: Optional pre-discovered list of ``(path, size, mtime)``
            tuples from :func:`_discover_audio_files`. If None, the function
            will discover them internally (performing a fresh tree walk).
            Passing the list avoids a duplicate directory traversal AND a
            redundant ``stat()`` per file — size and mtime come from the
            scandir-level attributes.
        cache: Optional ``ScanCache``. When provided, each scanned file
            (with sidecars) is written into the cache so the probe phase
            can skip the directory walk entirely on the next read.

    Returns:
        ``(rows, sidecar_map)`` where ``rows`` is a list of ``IndexRow`` and
        ``sidecar_map`` is a ``dict[Path, str]`` from source path to sidecar basenames.
    """
    if audio_files is None:
        audio_files = _discover_audio_files(input_path, excludes)
    total = len(audio_files)
    progress.log(f"Scanning {total} file(s)...")
    rows: list[IndexRow] = []
    sidecar_map: dict[Path, str] = {}

    lyrics_policy = getattr(preset, "lyrics", None) if preset is not None else None
    covers_policy = getattr(preset, "covers", None) if preset is not None else None

    # Throttle log_file output: only emit every 50 files so the UI stays
    # responsive even when scanning thousands of files. The final file always logs.
    for idx, (infile, file_size, mtime) in enumerate(audio_files, start=1):
        sidecar_basenames = _collect_sidecar_basenames(infile, lyrics_policy, covers_policy)
        sidecar_map[infile] = sidecar_basenames
        if cache is not None:
            cache.add(
                source_path=str(infile),
                file_size=file_size,
                mtime=mtime,
                sidecar_files=sidecar_basenames,
            )
        rows.append(
            IndexRow(
                source_path=str(infile),
                dest_path="",
                job_type="",
                file_size=file_size,
                sidecar_files=sidecar_basenames,
                mtime=mtime,
            )
        )
        is_last = (idx == total)
        # Log every 50 files + the final file to keep the log area informative
        # without spamming the display. The bar always advances.
        if is_last or idx % 50 == 0:
            if hasattr(progress, "log_file"):
                progress.log_file(f"  {infile.name} ({_format_bytes(file_size)})")
        progress.advance()

    if cache is not None:
        cache.commit()

    return rows, sidecar_map


def load_rows_from_cache(cache: "ScanCache") -> list[IndexRow]:
    """Build ``IndexRow`` objects from a ``ScanCache``.

    Used by the probe phase to skip the directory walk entirely: scan
    produced the cache, probe reads rows back as ``IndexRow`` objects
    with ``dest_path=""`` and ``job_type=""`` (the same shape
    ``scan_with_progress`` would have returned after a fresh walk).
    """
    rows: list[IndexRow] = []
    for source_path, file_size, mtime, sidecar_files in cache.iter_files():
        rows.append(
            IndexRow(
                source_path=source_path,
                dest_path="",
                job_type="",
                file_size=file_size,
                sidecar_files=sidecar_files,
                mtime=mtime,
            )
        )
    return rows


def _format_bytes(num_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if num_bytes >= 1 << 30:
        return f"{num_bytes / (1 << 30):.2f} GiB"
    if num_bytes >= 1 << 20:
        return f"{num_bytes / (1 << 20):.2f} MiB"
    if num_bytes >= 1 << 10:
        return f"{num_bytes / (1 << 10):.2f} KiB"
    return f"{num_bytes} B"
