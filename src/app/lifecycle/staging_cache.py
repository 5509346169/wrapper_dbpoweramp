"""app/lifecycle/staging_cache.py: StagingCache open/close wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.index.staging_cache import StagingCache


def open_staging_cache(
    tmp_dir: Path,
    input_path: Path,
    exclude: list[str],
) -> "StagingCache | None":
    """Try to open the most recent staging cache for the given args.

    Returns None if no valid cache exists or on error.
    """
    from src.index.staging_cache import StagingCache

    try:
        return StagingCache.open_latest(tmp_dir, input_path, exclude)
    except OSError as exc:
        print(f"warning: could not read staging cache: {exc}", file=__import__('sys').stderr)
        return None


def create_staging_cache(
    tmp_dir: Path,
    input_path: Path,
    exclude: list[str],
) -> "StagingCache | None":
    """Create a new staging cache for the given args.

    Returns None on error.
    """
    from src.index.staging_cache import StagingCache

    try:
        return StagingCache.create(tmp_dir, input_path, exclude)
    except OSError as exc:
        print(f"warning: could not create staging cache: {exc}", file=__import__('sys').stderr)
        return None


def close_staging_cache(cache: "StagingCache | None") -> None:
    """Safely close a staging cache (no-op if None)."""
    if cache is not None:
        try:
            cache.close()
        except Exception:
            pass
