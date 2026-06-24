"""execution/runner.py: Execute ConversionJob lists using the configured backend."""

from __future__ import annotations

import shutil
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Callable, Optional

from src.backends.base import ConversionBackend
from src.history.db import ConversionDB, DBWriteQueue
from src.models.types import ConversionJob, JobResult, JobStatus
from src.sidecars.manager import copy_covers, copy_lyrics
from src.ui.progress_view import ProgressSink, SubtaskID


class JobEventKind(str, Enum):
    """Picklable events workers push onto the shared event queue."""

    STARTED = "started"
    FINISHED = "finished"
    LOG = "log"
    ACTIVITY = "activity"


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


def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    """
    Verify the output file exists and has a reasonable size.

    Returns:
        (is_valid, error_message) - is_valid is True if file exists and has content.
    """
    if not job.outfile.exists():
        return False, f"Output file not found: {job.outfile}"

    size = job.outfile.stat().st_size
    if size == 0:
        return False, f"Output file is empty: {job.outfile}"

    return True, None


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    write_queue: DBWriteQueue,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """
    Execute a single ConversionJob.

    Args:
        job: The conversion job to execute.
        backend: The conversion backend to use.
        db_path: Path to the history SQLite database (for resume checks).
        write_queue: Queue for async DB writes (serializes concurrent writes).
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

    # Send activity event to update UI
    if events is not None:
        events.put((JobEventKind.ACTIVITY, job.job_type))
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
                # Verify output file before marking as success
                is_valid, verify_error = _verify_output_file(job)
                if not is_valid:
                    status = "FAILED"
                    error_msg = verify_error
                else:
                    copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                    copy_covers(job.infile, job.outfile, job.preset.covers)
                    write_queue.log_conversion(
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
                # Verify output file before marking as success
                is_valid, verify_error = _verify_output_file(job)
                if not is_valid:
                    result.status = "FAILED"
                    result.error_msg = verify_error
                else:
                    copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                    copy_covers(job.infile, job.outfile, job.preset.covers)
                    write_queue.log_conversion(
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


def _run_event_drain_thread(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
    stop_event: Event,
) -> None:
    """
    Background thread that continuously drains the event queue and updates the UI.
    Runs until stop_event is set.
    """
    while not stop_event.is_set():
        _drain_events_into_ui(events, progress, job_tasks)
        stop_event.wait(timeout=0.1)  # Poll every 100ms


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
        return summary, [], _make_event_queue(worker_model), DBWriteQueue(Path(db_path))

    write_queue = DBWriteQueue(Path(db_path))
    events = _make_event_queue(worker_model)

    if print_to_terminal:
        # When printing to terminal, use a direct stdout callback for verbose output
        def _direct_print_callback(line: str) -> None:
            print(line)
        stream_cb: Optional[Callable[[str], None]] = _direct_print_callback if verbose else None
    else:
        stream_cb = _build_stream_callback(events) if verbose else None

    ExecutorCls = ThreadPoolExecutor if worker_model == "thread" else ProcessPoolExecutor

    futures: list[Future] = []

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
                    write_queue,
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


def _drain_events_into_ui(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
) -> None:
    """
    Drain queued (JobEventKind, payload) tuples from workers and apply UI updates
    on the calling thread. Per-job bars are added on STARTED and removed on FINISHED.
    The job_tasks dict is updated in-place to track active in-flight jobs.

    STARTED events are only processed if the job is not already tracked (prevents
    duplicate bars if the same event is processed by multiple callers/drain cycles).
    FINISHED events always remove the bar (idempotent - safe if already removed)
    and advance the master bar count for real-time progress.
    ACTIVITY events update the activity indicator (copy/convert).
    """
    while True:
        try:
            kind, payload = events.get_nowait()
        except Empty:
            return
        infile_name = str(payload)
        if kind == JobEventKind.LOG:
            progress.log(infile_name)
        elif kind == JobEventKind.ACTIVITY:
            progress.set_activity(infile_name)
        elif kind == JobEventKind.STARTED:
            # Only add bar if not already tracking this job (prevents duplicates)
            if infile_name not in job_tasks:
                job_tasks[infile_name] = progress.start_subtask(infile_name)
        elif kind == JobEventKind.FINISHED:
            subtask_id = job_tasks.pop(infile_name, None)
            if subtask_id is not None:
                progress.finish_subtask(subtask_id)
                # Advance master bar immediately for real-time count update
                progress.advance()
