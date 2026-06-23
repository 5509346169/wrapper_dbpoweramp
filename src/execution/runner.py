"""execution/runner.py: Execute ConversionJob lists using the configured backend."""

from __future__ import annotations

import shutil
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Optional

from src.backends.base import ConversionBackend
from src.history.db import ConversionDB
from src.models.types import ConversionJob, JobResult, JobStatus
from src.sidecars.manager import copy_covers, copy_lyrics
from src.ui.progress_view import ProgressSink, SubtaskID


class JobEventKind(str, Enum):
    """Picklable events workers push onto the shared event queue."""

    STARTED = "started"
    FINISHED = "finished"
    LOG = "log"


def _make_event_queue(worker_model: str) -> Queue:
    """Build a thread/process-safe queue for cross-worker UI events."""
    if worker_model == "process":
        from multiprocessing import get_context

        # multiprocessing.Queue cannot be pickled into a spawn-based worker
        # (Windows default), so use a Manager to obtain a picklable proxy.
        manager = get_context().Manager()
        return manager.Queue()
    return Queue()


def _build_stream_callback(events: Queue) -> Optional[Callable[[str], None]]:
    """Build a stream_callback that forwards verbose lines to the main thread."""
    from functools import partial

    return partial(_push_log_event, events)


def _push_log_event(events: Queue, line: str) -> None:
    """Module-level picklable sink used by workers to enqueue verbose lines."""
    events.put((JobEventKind.LOG, line))


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """
    Execute a single ConversionJob.

    Args:
        job: The conversion job to execute.
        backend: The conversion backend to use.
        db_path: Path to the history SQLite database.
        force: If True, skip resume checks and force re-processing.
        stream_callback: Optional callback for streaming output line-by-line.
        events: Optional cross-process/thread queue for UI events. Workers push
            (JobEventKind.STARTED, infile_name) when they begin and
            (JobEventKind.FINISHED, infile_name) when they finish. The main
            thread drains the queue and updates the UI.

    Returns:
        A tuple of (status, infile_name, error_msg).
    """
    infile_name = job.infile.name

    db = ConversionDB(Path(db_path))

    if events is not None:
        events.put((JobEventKind.STARTED, infile_name))

    try:
        if job.job_type == "skip":
            status: JobStatus = "SKIPPED"
            error_msg: str | None = "lossy, leave"

        elif job.job_type == "copy":
            try:
                job.outfile.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(job.infile, job.outfile)
            except (shutil.Error, OSError) as e:
                print(f"[runner] copy failed for {job.infile} -> {job.outfile}: {e}")
                status = "FAILED"
                error_msg = str(e)
            else:
                copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                copy_covers(job.infile, job.outfile, job.preset.covers)
                db.log_conversion(
                    source=str(job.infile),
                    dest=str(job.outfile),
                    job_type=job.job_type,
                    command=None,
                    status="SUCCESS",
                )
                status = "SUCCESS"
                error_msg = None

        elif job.job_type == "convert":
            dest_exists = job.outfile.exists()

            if not force and db.should_skip(
                str(job.infile), str(job.outfile), job_type="convert", dest_file_exists=dest_exists
            ):
                status = "SKIPPED"
                error_msg = None
                return status, infile_name, error_msg

            job.outfile.parent.mkdir(parents=True, exist_ok=True)
            result = backend.run(job, stream_callback)

            if result.status == "SUCCESS":
                copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                copy_covers(job.infile, job.outfile, job.preset.covers)
                db.log_conversion(
                    source=str(job.infile),
                    dest=str(job.outfile),
                    job_type=job.job_type,
                    command=None,
                    status=result.status,
                    error_msg=result.error_msg,
                    stdout=result.stdout,
                )

            status = result.status
            error_msg = result.error_msg

        else:
            status = "FAILED"
            error_msg = f"unknown job_type: {job.job_type}"

    finally:
        db.close()
        if events is not None:
            events.put((JobEventKind.FINISHED, infile_name))

    return status, infile_name, error_msg


def run_all(
    jobs: list[ConversionJob],
    backend: ConversionBackend,
    db: ConversionDB,
    force: bool,
    workers: int,
    worker_model: str,
    verbose: bool,
    progress: ProgressSink,
) -> tuple[dict[str, int], list[Future], Queue]:
    """
    Execute a list of ConversionJobs using a thread or process pool.

    Args:
        jobs: List of conversion jobs to execute.
        backend: The conversion backend to use.
        db: The history database for logging and resume checks.
        force: If True, skip resume checks and force re-processing.
        workers: Maximum number of parallel workers.
        worker_model: Either "thread" for ThreadPoolExecutor or "process" for ProcessPoolExecutor.
        verbose: If True, enable verbose output streaming.
        progress: A ProgressSink used to report master-bar advances, per-job bars,
            and log lines. In parallel (workers > 1) mode the caller drains the
            shared event queue and forwards events here. In single-worker mode the
            events are drained inline alongside job completion.

    Returns:
        A tuple of (summary dict with success/skipped/failed counts, list of futures,
        events queue). The events queue carries (JobEventKind, payload) tuples from
        workers; callers in parallel mode drain it between iterations to update
        per-job UI state without ever touching rich from inside a worker.
    """
    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    if not jobs:
        return summary, [], _make_event_queue(worker_model)

    events = _make_event_queue(worker_model)
    stream_cb: Optional[Callable[[str], None]] = (
        _build_stream_callback(events) if verbose else None
    )

    ExecutorCls = ThreadPoolExecutor if worker_model == "thread" else ProcessPoolExecutor

    futures: list[Future] = []

    with ExecutorCls(max_workers=workers) as executor:
        futures = [
            executor.submit(
                run_job,
                job,
                backend,
                str(db.db_path),
                force,
                stream_cb,
                events,
            )
            for job in jobs
        ]

        if workers == 1:
            for future in as_completed(futures):
                _drain_events_into_ui(events, progress)
                status, infile_name, error_msg = future.result()

                if status == "SUCCESS":
                    summary["success"] += 1
                elif status == "SKIPPED":
                    summary["skipped"] += 1
                else:
                    summary["failed"] += 1

                progress.advance()

    return summary, futures, events


def _drain_events_into_ui(events: Queue, progress: ProgressSink) -> dict[str, SubtaskID]:
    """
    Drain queued (JobEventKind, payload) tuples from workers and apply UI updates
    on the calling thread. Per-job bars are added on STARTED and removed on FINISHED.
    Returns a dict mapping infile_name to SubtaskID for active in-flight jobs.
    """
    job_tasks: dict[str, SubtaskID] = {}
    while True:
        try:
            kind, payload = events.get_nowait()
        except Empty:
            return job_tasks
        infile_name = str(payload)
        if kind == JobEventKind.LOG:
            progress.log(infile_name)
        elif kind == JobEventKind.STARTED:
            job_tasks[infile_name] = progress.start_subtask(infile_name)
        elif kind == JobEventKind.FINISHED:
            subtask_id = job_tasks.pop(infile_name, None)
            if subtask_id is not None:
                progress.finish_subtask(subtask_id)
    return job_tasks
