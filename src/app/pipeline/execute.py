"""app/pipeline/execute.py: Execute phase — Rich/Verbose sink + run_all + futures draining."""

from __future__ import annotations

from concurrent.futures import as_completed
from typing import TYPE_CHECKING

from src.execution.runner import _drain_events_into_ui
from src.execution.run_all import run_all
from src.history.db import DBWriteQueue
from src.ui.progress_view import (
    NullProgressSink,
    RichProgressSink,
    SubtaskID,
)

if TYPE_CHECKING:
    from src.app.context import AppContext, MutablePhaseState
    from src.ui.progress_view import ProgressSink


def execute_phases(
    phases: list[tuple[str, list]],
    ctx: "AppContext",
    phase_state: "MutablePhaseState",
    total_bytes: int = 0,
    sink: "ProgressSink | None" = None,
) -> tuple[dict[str, int], "DBWriteQueue | None"]:
    """Execute all phases through run_all, handling both verbose and rich sink modes.

    Args:
        phases: List of (phase_label, batch) tuples.
        ctx: The application context.
        phase_state: MutablePhaseState holding prefilter_skips and other phase results.
        total_bytes: Total bytes for the rich progress bar.
        sink: Optional externally-built ProgressSink. When provided, this sink
            is reused across the Skipping and per-phase bars so a single Live
            instance stays alive for the lifetime of the caller's prefilter →
            execute flow. When None (default), this function builds its own
            RichProgressSink/NullProgressSink based on ``ctx.verbose`` and is
            responsible for tearing it down via ``sink.stop()`` on exit.

    Returns:
        A tuple of (summary dict with success/skipped/failed, write_queue or None).
    """
    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
    write_queue: "DBWriteQueue | None" = None
    prefilter_skips = phase_state.prefilter_skips

    # When the caller hands us a sink, we are a *guest* of its Live renderer —
    # we may use it (start_phase / advance / stop_phase) but we MUST NOT call
    # sink.stop() because the caller will reuse or tear down the sink itself.
    # Track that with ``owns_sink`` so the verbose and rich branches can both
    # honor it.
    owns_sink = sink is None

    if ctx.verbose:
        sink_for_run: "ProgressSink"
        if sink is None:
            sink_for_run = NullProgressSink()
            sink = sink_for_run
        else:
            sink_for_run = sink
        progress_active = False
        if prefilter_skips:
            print(f"[Skipping] {len(prefilter_skips)} already-converted file(s)")
        for phase_label, batch in phases:
            print(f"Phase — {phase_label} ({len(batch)} file(s))")
        if phases:
            flat_jobs = [j for _, batch in phases for j in batch]
            phase_summary, _, _, write_queue = run_all(
                jobs=flat_jobs,
                backend=ctx.backend,
                db_path=str(ctx.db_path),
                force=ctx.args.force,
                workers=ctx.workers,
                worker_model=ctx.worker_model,
                verbose=ctx.verbose,
                progress=sink_for_run,
                print_to_terminal=ctx.verbose,
            )
        else:
            write_queue = DBWriteQueue(ctx.db_path, ctx.worker_model)
        summary = phase_summary
    else:
        if sink is None:
            sink = RichProgressSink(total_bytes=total_bytes)
        if prefilter_skips:
            sink.start_phase("Skipping", total=len(prefilter_skips))
            for job in prefilter_skips:
                sink.advance()
                sink.log_file(f"  {job.infile.name}")
            sink.stop_phase()
            sink.log(f"Skipped {len(prefilter_skips)} already-converted file(s)")
        phase_summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
        write_queue = None
        for phase_label, batch in phases:
            sink.start_phase(phase_label, total=len(batch))
            if not batch:
                sink.stop_phase()
                continue
            conv_summary, futures, events, write_queue = run_all(
                jobs=batch,
                backend=ctx.backend,
                db_path=str(ctx.db_path),
                force=ctx.args.force,
                workers=ctx.workers,
                worker_model=ctx.worker_model,
                verbose=ctx.verbose,
                progress=sink,
                print_to_terminal=ctx.verbose,
            )
            if ctx.workers > 1:
                job_tasks: dict[str, SubtaskID] = {}
                remaining = list(futures)
                while remaining:
                    _drain_events_into_ui(events, sink, job_tasks)
                    for future in list(as_completed(remaining)):
                        remaining.remove(future)
                        status, infile_name, error_msg = future.result()
                        if status == "SUCCESS":
                            conv_summary["success"] += 1
                        elif status == "SKIPPED":
                            conv_summary["skipped"] += 1
                        else:
                            conv_summary["failed"] += 1
            for k in phase_summary:
                phase_summary[k] += conv_summary.get(k, 0)
            sink.stop_phase()
        progress_active = True
        summary = phase_summary

    if owns_sink and not ctx.verbose:
        sink.stop()  # type: ignore[union-attr]

    if write_queue is not None:
        write_queue.flush()

    # Add pre-filtered skips to the summary
    summary["skipped"] += len(prefilter_skips)

    return summary, write_queue
