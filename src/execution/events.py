"""execution/events.py: Event types and queue helpers for cross-worker UI updates."""

from __future__ import annotations

from enum import Enum
from functools import partial
from multiprocessing import get_context
from queue import Queue
from typing import Callable, Optional


class JobEventKind(str, Enum):
    """Picklable events workers push onto the shared event queue."""

    STARTED = "started"
    FINISHED = "finished"
    LOG = "log"
    ACTIVITY = "activity"


def _make_event_queue(worker_model: str) -> Queue:
    """Build a thread/process-safe queue for cross-worker UI events."""
    if worker_model == "process":
        # multiprocessing.Queue cannot be pickled into a spawn-based worker
        # (Windows default), so use a Manager to obtain a picklable proxy.
        manager = get_context().Manager()
        return manager.Queue()
    return Queue()


def _push_log_event(events: Queue, line: str) -> None:
    """Module-level picklable sink used by workers to enqueue verbose lines."""
    events.put((JobEventKind.LOG, line))


def _build_stream_callback(events: Queue) -> Optional[Callable[[str], None]]:
    """Build a stream_callback that forwards verbose lines to the main thread."""
    return partial(_push_log_event, events)
