"""app/pipeline/scan.py: Scan phase — directory walk + optional scan-cache orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint

from src.index.scanner import (
    IndexRow,
    _discover_audio_files,
    load_rows_from_cache,
    scan_with_progress,
)
from src.models.types import ConversionJob, LossyAction, PresetConfig
from src.ui.progress_view import RichProgressSink, VerboseProgressSink

if TYPE_CHECKING:
    from src.app.context import AppContext
    from src.index.scan_cache import ScanCache
    from src.ui.progress_view import ProgressSink


@dataclass
class ScanResult:
    """Output of the scan phase."""

    rows: list[IndexRow]
    sidecar_map: dict[Path, str]
    scan_cache: "ScanCache | None"
    total_files: int
    cache_hit: bool


def scan(
    ctx: "AppContext",
    progress: "ProgressSink | None" = None,
) -> ScanResult:
    """Run the scan phase: directory walk + optional scan-cache reuse.

    Two-tier strategy:
      a) If a matching scan-cache exists in ./tmp/, load rows from it — skipping
         the directory walk entirely.
      b) Otherwise, walk the directory with _discover_audio_files, pass the cache
         to scan_with_progress so it gets populated, then proceed.

    Args:
        ctx: The application context.
        progress: Optional progress sink (used if verbose is False).

    Returns:
        A ``ScanResult`` with rows, sidecar_map, scan_cache, and metadata.
    """
    from src.app.lifecycle.scan_cache import close_scan_cache, create_scan_cache, open_scan_cache

    cache_enabled = (
        not getattr(ctx.args, "no_scan_cache", False)
        and ctx.args.input is not None
    )

    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)

    scan_cache: "ScanCache | None" = None
    cache_hit = False
    sink: "ProgressSink | None" = None

    # Try cache first
    if cache_enabled:
        scan_cache = open_scan_cache(tmp_dir, ctx.args.input, ctx.args.exclude)

    if scan_cache is not None:
        # Cache hit
        rows = list(load_rows_from_cache(scan_cache))
        total_files = len(rows)
        cache_hit = True
        sidecar_map = {Path(r.source_path): r.sidecar_files for r in rows}

        if ctx.verbose:
            sink = VerboseProgressSink()
            sink.log_phase("Scanning")
            sink.log_file(f"Cache hit: {total_files} file(s) from {scan_cache.db_path.name}")
        else:
            sink = RichProgressSink()
            sink.start_phase("Scanning (cached)", total=total_files)
            for _ in range(total_files):
                sink.advance()
        if sink:
            sink.stop()

        rprint(
            f" [green]{len(rows)} file(s) loaded from scan-cache "
            f"{scan_cache.db_path.name}[/green]"
        )
    else:
        # Cache miss — walk the directory
        audio_files = _discover_audio_files(ctx.args.input, ctx.args.exclude)
        total_files = len(audio_files)

        if cache_enabled:
            scan_cache = create_scan_cache(tmp_dir, ctx.args.input, ctx.args.exclude)

        if ctx.verbose:
            sink = VerboseProgressSink()
            sink.log_phase("Scanning")
            sink.log_file(f"Found {total_files} audio file(s)")
        else:
            sink = RichProgressSink()
            sink.start_phase("Scanning", total=total_files)

        rows, sidecar_map = scan_with_progress(
            input_path=ctx.args.input,
            excludes=ctx.args.exclude,
            preset=ctx.preset,
            progress=sink,
            audio_files=audio_files,
            cache=scan_cache,
        )
        if sink:
            sink.stop()

        rprint(f" [green]{len(rows)} file(s) found[/green]")
        if scan_cache is not None:
            rprint(f" [cyan]Scan cache:[/cyan] {scan_cache.db_path}")

    if not rows:
        print("No audio files found.")

    return ScanResult(
        rows=rows,
        sidecar_map=sidecar_map,
        scan_cache=scan_cache,
        total_files=total_files,
        cache_hit=cache_hit,
    )
