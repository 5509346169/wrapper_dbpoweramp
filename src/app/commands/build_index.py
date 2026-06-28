"""commands/build_index.py: --build-index command — scan + enrich + write index DB, then exit."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint

from src.index.builder import IndexBuilder
from src.index.scanner import (
    _discover_audio_files,
    load_rows_from_cache,
    scan_with_progress,
)
from src.jobs.builder import enrich_index_rows_streaming
from src.models.types import LossyAction
from src.ui.progress_view import RichProgressSink, VerboseProgressSink

if TYPE_CHECKING:
    from src.app.context import AppContext


def run(ctx: "AppContext") -> int:
    """Build an index database without converting, then exit."""
    from src.app.lifecycle.signals import install_signal_guard
    from src.app.lifecycle.scan_cache import close_scan_cache, create_scan_cache, open_scan_cache
    from src.app.pipeline.reporting import format_bytes

    with install_signal_guard() as guard:
        tmp_dir = Path("tmp")
        tmp_dir.mkdir(exist_ok=True)

        scan_cache = None
        cache_enabled = not getattr(ctx.args, "no_scan_cache", False)

        if cache_enabled:
            scan_cache = open_scan_cache(tmp_dir, ctx.args.input, ctx.args.exclude)

        try:
            if scan_cache is not None:
                rows = list(load_rows_from_cache(scan_cache))
                total_files = len(rows)
                if ctx.verbose:
                    sink = VerboseProgressSink()
                    sink.log_phase("Scanning")
                    sink.log_file(f"Cache hit: {total_files} file(s) from {scan_cache.db_path.name}")
                else:
                    sink = RichProgressSink()
                    sink.start_phase("Scanning (cached)", total=total_files)
                    for _ in range(total_files):
                        sink.advance()
                sink.stop()
                rprint(
                    f" [green]{len(rows)} file(s) loaded from scan-cache "
                    f"{scan_cache.db_path.name}[/green]"
                )
            else:
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
                rows, _ = scan_with_progress(
                    input_path=ctx.args.input,
                    excludes=ctx.args.exclude,
                    preset=ctx.preset,
                    progress=sink,
                    audio_files=audio_files,
                    cache=scan_cache,
                )
                sink.stop()
                rprint(f" [green]{len(rows)} file(s) found[/green]")
                if scan_cache is not None:
                    rprint(f" [cyan]Scan cache:[/cyan] {scan_cache.db_path}")

            if not rows:
                print("No audio files found.")
                return 0

            if ctx.args.input.is_file():
                input_root = ctx.args.input.parent
            else:
                input_root = ctx.args.input

            source_root = ctx.args.source_path if ctx.args.source_path is not None else None

            if ctx.verbose:
                sink = VerboseProgressSink()
                sink.log_phase("Probing")
            else:
                sink = RichProgressSink()

            lossy_action: LossyAction | None = None
            if ctx.args.lossy_action is not None:
                lossy_action = LossyAction(ctx.args.lossy_action)

            index_builder = IndexBuilder(ctx.args.build_index)

            enrich_index_rows_streaming(
                scan_rows=rows,
                input_root=input_root,
                source_root=source_root,
                output_root=ctx.args.output,
                preset=ctx.preset,
                lossy_action=lossy_action,
                no_lossy_check=ctx.args.no_lossy_check,
                probe_workers=ctx.settings.execution.probe_workers,
                progress=sink,
                index_builder=index_builder,
            )

            index_builder.commit()
            sink.stop()

            summary = index_builder.get_summary()
            rprint()
            rprint(f"[green]Index built successfully:[/green] {ctx.args.build_index}")
            rprint(f"  Total files: {summary['total']}")
            rprint(f"  Total size: {format_bytes(summary['total_bytes'])}")
            rprint(f"  Lossy files: {summary['lossy']}")
            for job_type, count in summary["by_type"].items():
                rprint(f"  {job_type}: {count}")

            index_builder.close()
            return 0

        finally:
            close_scan_cache(scan_cache)
