"""commands/run_pipeline.py: The main pipeline command — scan + enrich + prefilter + execute."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.ui.progress_view import RichProgressSink

if TYPE_CHECKING:
    from src.app.context import AppContext, MutablePhaseState


def run(ctx: "AppContext") -> int:
    """Run the full pipeline: scan → enrich → prefilter → execute."""
    from src.app.context import MutablePhaseState
    from src.app.lifecycle.signals import install_signal_guard
    from src.app.lifecycle.tempdir import cleanup_index, setup_temp_dir
    from src.app.lifecycle.scan_cache import close_scan_cache
    from src.app.pipeline.enrich import enrich
    from src.app.pipeline.execute import execute_phases
    from src.app.pipeline.jobs import build_jobs, check_lossy_gate
    from src.app.pipeline.phases import run_jobs_by_phase
    from src.app.pipeline.prefilter import prefilter_jobs
    from src.app.pipeline.reporting import print_summary
    from src.app.pipeline.scan import scan
    from src.index.builder import IndexBuilder

    tmp_dir, index_db_path = setup_temp_dir()
    phase_state = MutablePhaseState()

    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
    exc_info: str | None = None

    with install_signal_guard() as guard:
        # ── Scan ──────────────────────────────────────────────────────────────
        scan_result = scan(ctx)

        if not scan_result.rows:
            close_scan_cache(scan_result.scan_cache)
            return 0

        # ── Enrich ───────────────────────────────────────────────────────────
        input_root: Path
        if ctx.args.input.is_file():
            input_root = ctx.args.input.parent
        else:
            input_root = ctx.args.input

        source_root = ctx.args.source_path if ctx.args.source_path is not None else None

        index_builder: IndexBuilder | None = None
        if index_db_path is not None:
            try:
                index_builder = IndexBuilder(index_db_path)
            except OSError as exc:
                print(f"warning: could not open index DB {index_db_path}: {exc}", file=__import__('sys').stderr)

        enriched_rows, lossy_files_found = enrich(
            scan_rows=scan_result.rows,
            input_root=input_root,
            source_root=source_root,
            output_root=ctx.args.output,
            ctx=ctx,
            progress=RichProgressSink() if not ctx.verbose else None,
            index_builder=index_builder,
        )

        if index_builder is not None:
            index_builder.commit()
            from rich import print as rprint
            rprint(f"[cyan]Index:[/cyan] {index_db_path}")
            index_builder.close()
            db_rows = list(IndexBuilder(index_db_path).iter_rows())
            source_rows = db_rows
        else:
            source_rows = enriched_rows

        # ── Build jobs ───────────────────────────────────────────────────────
        jobs = build_jobs(source_rows, ctx)

        # ── Lossy gate ──────────────────────────────────────────────────────
        if lossy_files_found:
            check_lossy_gate(len(lossy_files_found), ctx)

        # ── Pre-filter ──────────────────────────────────────────────────────
        pending_jobs, skipped_jobs = prefilter_jobs(jobs, ctx)
        phase_state.pending_jobs = pending_jobs
        phase_state.skipped_jobs = skipped_jobs

        if ctx.execution_mode.value == "phased":
            prefilter_skips = skipped_jobs
            pending_for_pool = [j for j in pending_jobs if j.job_type != "skip"]
        else:
            prefilter_skips = []
            pending_for_pool = pending_jobs

        phase_state.prefilter_skips = prefilter_skips

        total_bytes = sum(r.file_size for r in source_rows)

        # ── Execute ──────────────────────────────────────────────────────────
        phases = run_jobs_by_phase(pending_for_pool, ctx)

        summary, _ = execute_phases(phases, ctx, phase_state, total_bytes=total_bytes)
        print_summary(summary)

        # ── Cleanup ───────────────────────────────────────────────────────────
        close_scan_cache(scan_result.scan_cache)

        cleanup_index(
            db_path=index_db_path,
            failed_count=summary.get("failed", 0),
            exception_info=exc_info,
            interrupted=guard.interrupted,
        )

        return 0
