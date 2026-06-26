"""execution/event_drain.py: Drain worker events into the UI."""

from __future__ import annotations

from queue import Empty, Queue
from threading import Event, Thread

from src.ui.progress_view import ProgressSink, SubtaskID

from src.execution.events import JobEventKind


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
