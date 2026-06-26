"""audio/cascade.py: Three-tier lossy detection for a single file.

Tiers (in order):
  1. Extension — unambiguous extensions resolved immediately.
  2. Folder-name heuristic — lossy token in any parent directory.
  3. mutagen metadata probe — only for ambiguous extensions (.m4a, etc.).

Tier functions are looked up through the :mod:`src.audio.inspector` shim at
call time so existing tests (which monkey-patch
``src.audio.inspector._is_lossy_by_mutagen`` etc.) keep working without
modification.

The cascade runs **per file** — each worker thread walks its assigned
file through all three tiers in order, falling through to the next tier
only when the current one returns ``None`` (i.e. "unknown, can't decide").
This avoids the previous design of three sequential phases (all files
through Tier 1, then leftovers through Tier 2, then remaining through
Tier 3) which produced visual "stalls" when a tier finished and the next
started. Per-file cascade keeps every worker thread busy on whatever
tier its file needs.

A ``CascadeTier`` enum is returned alongside the boolean so the caller
can update progress-bar labels (Extension -> Folder -> Mutagen) as the
workload mix shifts over the course of the run.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class CascadeTier(Enum):
    """Which tier resolved a file's lossy status.

    Useful for telemetry/progress display: when most results are coming
    back at ``EXTENSION`` the workload is cheap; when most come back at
    ``MUTAGEN`` the workload is filesystem-bound.
    """

    EXTENSION = "extension"
    FOLDER = "folder"
    MUTAGEN = "mutagen"


def _resolve_tier(shim_name: str, fallback):
    """Return ``getattr(src.audio.inspector, shim_name)`` if present, else ``fallback``."""
    import src.audio.inspector as _shim

    fn = getattr(_shim, shim_name, None)
    return fn if fn is not None else fallback


def is_lossy(file: Path) -> bool:
    """Three-tier lossy detection for a single file.

    Returns True if the file is lossy, False if confirmed lossless.
    Raises ProbeError only when mutagen is invoked and fails.
    """
    # Import here (not at module load) so the resolver sees any
    # monkey-patching done by tests on the shim module.
    from src.audio.extensions import _is_lossy_by_ext as _ext_impl
    from src.audio.folder_heuristic import _is_lossy_by_folder as _folder_impl
    from src.audio.mutagen_probe import _is_lossy_by_mutagen as _mutagen_impl

    _is_lossy_by_ext: Callable[[Path], Optional[bool]] = _resolve_tier(
        "_is_lossy_by_ext", _ext_impl
    )
    _is_lossy_by_folder: Callable[[Path], Optional[bool]] = _resolve_tier(
        "_is_lossy_by_folder", _folder_impl
    )
    _is_lossy_by_mutagen: Callable[[Path], bool] = _resolve_tier(
        "_is_lossy_by_mutagen", _mutagen_impl
    )

    # Tier 1
    ext_result = _is_lossy_by_ext(file)
    if ext_result is not None:
        return ext_result

    # Tier 2
    folder_result = _is_lossy_by_folder(file)
    if folder_result is not None:
        return folder_result

    # Tier 3 — the only path that hits the filesystem
    return _is_lossy_by_mutagen(file)


def cascade_with_tier(file: Path) -> tuple[bool, CascadeTier]:
    """Per-file cascade that also reports which tier resolved the answer.

    Identical logic to :func:`is_lossy`, but returns a ``(result, tier)``
    tuple so the probe orchestrator can update UI labels based on the
    mix of tiers seen so far.

    Raises ProbeError only when mutagen is invoked and fails.
    """
    # Import here (not at module load) so the resolver sees any
    # monkey-patching done by tests on the shim module.
    from src.audio.extensions import _is_lossy_by_ext as _ext_impl
    from src.audio.folder_heuristic import _is_lossy_by_folder as _folder_impl
    from src.audio.mutagen_probe import _is_lossy_by_mutagen as _mutagen_impl

    _is_lossy_by_ext: Callable[[Path], Optional[bool]] = _resolve_tier(
        "_is_lossy_by_ext", _ext_impl
    )
    _is_lossy_by_folder: Callable[[Path], Optional[bool]] = _resolve_tier(
        "_is_lossy_by_folder", _folder_impl
    )
    _is_lossy_by_mutagen: Callable[[Path], bool] = _resolve_tier(
        "_is_lossy_by_mutagen", _mutagen_impl
    )

    # Tier 1
    ext_result = _is_lossy_by_ext(file)
    if ext_result is not None:
        return ext_result, CascadeTier.EXTENSION

    # Tier 2
    folder_result = _is_lossy_by_folder(file)
    if folder_result is not None:
        return folder_result, CascadeTier.FOLDER

    # Tier 3 — the only path that hits the filesystem
    return _is_lossy_by_mutagen(file), CascadeTier.MUTAGEN
