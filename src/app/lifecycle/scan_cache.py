"""app/lifecycle/scan_cache.py: ScanCache open/close wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.index.scan_cache import ScanCache


def open_scan_cache(
    tmp_dir: Path,
    input_path: Path,
    exclude: list[str],
) -> "ScanCache | None":
    """Try to open the most recent valid scan cache for the given args.

    Returns None if no valid cache exists or on error.
    """
    from src.index.scan_cache import ScanCache

    try:
        return ScanCache.open_latest(tmp_dir, input_path, exclude)
    except OSError as exc:
        print(f"warning: could not read scan-cache: {exc}", file=__import__('sys').stderr)
        return None


def create_scan_cache(
    tmp_dir: Path,
    input_path: Path,
    exclude: list[str],
) -> "ScanCache | None":
    """Create a new scan cache for the given args.

    Returns None on error.
    """
    from src.index.scan_cache import ScanCache

    try:
        return ScanCache.create(tmp_dir, input_path, exclude)
    except OSError as exc:
        print(f"warning: could not create scan-cache: {exc}", file=__import__('sys').stderr)
        return None


def close_scan_cache(cache: "ScanCache | None") -> None:
    """Safely close a scan cache (no-op if None)."""
    if cache is not None:
        try:
            cache.close()
        except Exception:
            pass
