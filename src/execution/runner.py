"""execution/runner.py: Backward-compatibility shim.

The implementation has been split into:

* :mod:`src.execution.events`      — JobEventKind and queue helpers
* :mod:`src.execution.run_job`    — single-job execution (copy/convert/skip)
* :mod:`src.execution.event_drain` — drain worker events into the UI
* :mod:`src.execution.run_all`    — thread/process pool orchestrator

This module re-exports the same public/private names from those locations
so existing imports (e.g. ``from src.execution.runner import run_all``)
continue to work.
"""

from src.execution.event_drain import _drain_events_into_ui
from src.execution.events import (
    JobEventKind,
    _build_stream_callback,
    _make_event_queue,
    _push_log_event,
)
from src.execution.run_all import run_all
from src.execution.run_job import _verify_output_file, run_job

__all__ = [
    "JobEventKind",
    "_build_stream_callback",
    "_drain_events_into_ui",
    "_make_event_queue",
    "_push_log_event",
    "_verify_output_file",
    "run_all",
    "run_job",
]
