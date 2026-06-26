"""audio/batch.py: Batch probe utilities for the lossy-detection cascade.

Tier functions are looked up through the :mod:`src.audio.inspector` shim at
call time so existing tests (which monkey-patch
``src.audio.inspector._is_lossy_by_mutagen`` etc.) keep working without
modification.
"""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional


def _resolve_tier(shim_name: str, fallback: Callable) -> Callable:
    """Return ``getattr(src.audio.inspector, shim_name)`` if present, else ``fallback``."""
    import src.audio.inspector as _shim

    fn = getattr(_shim, shim_name, None)
    return fn if fn is not None else fallback


def _classify_by_ext_and_folder(files: list[Path]) -> dict[Path, Optional[bool]]:
    """Apply tiers 1 and 2 to every file in one synchronous pass.

    Returns a dict mapping each file to True/False (tiers 1-2 resolved)
    or None (needs Tier 3 probe).
    """
    from src.audio.extensions import _is_lossy_by_ext as _ext_impl
    from src.audio.folder_heuristic import _is_lossy_by_folder as _folder_impl

    _is_lossy_by_ext = _resolve_tier("_is_lossy_by_ext", _ext_impl)
    _is_lossy_by_folder = _resolve_tier("_is_lossy_by_folder", _folder_impl)

    result: dict[Path, Optional[bool]] = {}
    for f in files:
        ext_result = _is_lossy_by_ext(f)
        if ext_result is not None:
            result[f] = ext_result
            continue
        folder_result = _is_lossy_by_folder(f)
        if folder_result is not None:
            result[f] = folder_result
            continue
        result[f] = None  # needs Tier 3
    return result


def probe_generator(
    files: list[Path], workers: int
) -> tuple[Future, ...]:
    """Launch mutagen probes only for the Tier-3 ambiguous subset.

    Extension and folder-name checks are applied synchronously in the calling
    thread before the executor is even created, so no worker time is wasted
    on unambiguous files.
    """
    from src.audio.mutagen_probe import _is_lossy_by_mutagen as _mutagen_impl

    _is_lossy_by_mutagen = _resolve_tier("_is_lossy_by_mutagen", _mutagen_impl)

    classified = _classify_by_ext_and_folder(files)
    ambiguous_files = [f for f, v in classified.items() if v is None]

    if not ambiguous_files:
        return ()

    def probe_one(file: Path) -> tuple[Path, bool]:
        return (file, _is_lossy_by_mutagen(file))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(probe_one, f) for f in ambiguous_files]
    return tuple(futures)


def probe_many(
    files: list[Path], workers: int
) -> dict[Path, bool]:
    """Three-tier lossy detection for a batch of files (blocking convenience wrapper).

    Extension and folder-name are applied synchronously first; mutagen is used
    only for the ambiguous subset (.m4a, etc.) in a thread pool.
    """
    classified = _classify_by_ext_and_folder(files)
    ambiguous_files = [f for f, v in classified.items() if v is None]

    # Resolve ambiguous files in parallel
    ambiguous_results: dict[Path, bool] = {}
    if ambiguous_files:
        for future in as_completed(probe_generator(ambiguous_files, workers)):
            f, result = future.result()
            ambiguous_results[f] = result

    # Merge results
    final: dict[Path, bool] = {}
    for f, v in classified.items():
        if v is not None:
            final[f] = v
        else:
            final[f] = ambiguous_results[f]
    return final
