"""commands/run_from_index.py: --index command — run conversions from a pre-built index DB."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.index.builder import IndexBuilder
from src.index.scanner import IndexRow
from src.models.types import ConversionJob
from src.ui.progress_view import RichProgressSink, VerboseProgressSink

if TYPE_CHECKING:
    from src.app.context import AppContext


def run(ctx: "AppContext") -> int:
    """Run conversions using a pre-built index database, skipping scan/probe phases."""
    from src.app.context import MutablePhaseState
    from src.app.lifecycle.signals import install_signal_guard
    from src.app.pipeline.execute import execute_phases
    from src.app.pipeline.jobs import build_jobs, check_lossy_gate
    from src.app.pipeline.phases import run_jobs_by_phase
    from src.app.pipeline.prefilter import prefilter_jobs
    from src.app.pipeline.reporting import format_bytes, print_summary

    # Open the existing index
    try:
        index_builder = IndexBuilder.from_existing(ctx.args.index)
    except FileNotFoundError:
        print(f"error: index database not found: {ctx.args.index}", file=__import__('sys').stderr)
        return 1

    source_rows = list(index_builder.iter_rows())
    summary_info = index_builder.get_summary()
    index_builder.close()

    if not source_rows:
        print("Index is empty.")
        return 0

    print(f"Loaded index: {ctx.args.index}")
    print(f"  Total files: {summary_info['total']}")
    print(f"  Total size: {format_bytes(summary_info['total_bytes'])}")
    print(f"  Lossy files: {summary_info['lossy']}")

    jobs = build_jobs(source_rows, ctx)

    # Lossy gate
    if summary_info["lossy"] > 0:
        check_lossy_gate(summary_info["lossy"], ctx)

    with install_signal_guard() as guard:
        # Pre-filter jobs
        pending_jobs, skipped_jobs = prefilter_jobs(jobs, ctx)
        phase_state = MutablePhaseState()
        phase_state.pending_jobs = pending_jobs
        phase_state.skipped_jobs = skipped_jobs

        if ctx.execution_mode.value == "phased":
            prefilter_skips = skipped_jobs
            pending_for_pool = [j for j in pending_jobs if j.job_type != "skip"]
        else:
            prefilter_skips = []
            pending_for_pool = pending_jobs

        phase_state.prefilter_skips = prefilter_skips

        total_bytes = summary_info["total_bytes"]
        phases = run_jobs_by_phase(pending_for_pool, ctx)

        summary, _ = execute_phases(phases, ctx, phase_state, total_bytes=total_bytes)
        print_summary(summary)
        return 0
