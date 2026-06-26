"""execution/run_all.py: Top-level orchestrator — dispatch a list of jobs via a thread/process pool."""

from __future__ import annotations

from concurrent.futures import (
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from typing import Callable, Optional

from src.backends.base import ConversionBackend
from src.history.db import DBWriteQueue
from src.models.types import ConversionJob
from src.ui.progress_view import ProgressSink, SubtaskID

from src.execution.event_drain import (
    _drain_events_into_ui,
    _run_event_drain_thread,
)
from src.execution.events import _build_stream_callback, _make_event_queue
from src.execution.run_job import run_job


def run_all(
    jobs: list[ConversionJob],
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    workers: int,
    worker_model: str,
    verbose: bool,
    progress: ProgressSink,
    print_to_terminal: bool = False,
) -> tuple[dict[str, int], list[Future], Queue, DBWriteQueue]:
    """
    Execute a list of ConversionJobs using a thread or process pool.

    Args:
        jobs: List of conversion jobs to execute.
        backend: The conversion backend to use.
        db_path: Path to the history SQLite database.
        force: If True, skip resume checks and force re-processing.
        workers: Maximum number of parallel workers.
        worker_model: Either "thread" for ThreadPoolExecutor or "process" for ProcessPoolExecutor.
        verbose: If True, enable verbose output streaming.
        print_to_terminal: If True, print verbose output directly to stdout instead of
            via the progress sink (for --verbose mode without progress bar).
        progress: A ProgressSink used to report master-bar advances, per-job bars,
            and log lines. In parallel (workers > 1) mode the caller drains the
            shared event queue and forwards events here. In single-worker mode the
            events are drained inline alongside job completion.

    Returns:
        A tuple of (summary dict with success/skipped/failed counts, list of futures,
        events queue, write queue). The events queue carries (JobEventKind, payload)
        tuples from workers; callers in parallel mode drain it between iterations to
        update per-job UI state without ever touching rich from inside a worker.
        The write queue should be flushed after all jobs complete.
    """
    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    if not jobs:
        return summary, [], _make_event_queue(worker_model), DBWriteQueue(Path(db_path), worker_model)

    write_queue = DBWriteQueue(Path(db_path), worker_model)
    events = _make_event_queue(worker_model)

    if print_to_terminal:
        # When printing to terminal, use a direct stdout callback for verbose output
        def _direct_print_callback(line: str) -> None:
            print(line)
        stream_cb: Optional[Callable[[str], None]] = _direct_print_callback if verbose else None
    else:
        stream_cb = _build_stream_callback(events) if verbose else None

    ExecutorCls = ThreadPoolExecutor if worker_model == "thread" else ProcessPoolExecutor

    # Track in-flight jobs for proper subtask bar management
    job_tasks: dict[str, SubtaskID] = {}

    # Start background thread to continuously drain events for real-time UI updates
    stop_drain = Event()
    drain_thread = Thread(
        target=_run_event_drain_thread,
        args=(events, progress, job_tasks, stop_drain),
        daemon=True,
    )
    drain_thread.start()

    try:
        with ExecutorCls(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    run_job,
                    job,
                    backend,
                    db_path,
                    force,
                    stream_cb,
                    events,
                )
                for job in jobs
            ]

            if workers == 1:
                for future in as_completed(futures):
                    _drain_events_into_ui(events, progress, job_tasks)
                    status, infile_name, error_msg = future.result()

                    if status == "SUCCESS":
                        summary["success"] += 1
                    elif status == "SKIPPED":
                        summary["skipped"] += 1
                    else:
                        summary["failed"] += 1
                    # Note: advance() is already called by drain when FINISHED event is processed
    finally:
        # Stop the drain thread
        stop_drain.set()
        drain_thread.join(timeout=1.0)
        # Final drain to capture any remaining events
        _drain_events_into_ui(events, progress, job_tasks)

    return summary, futures, events, write_queue
