"""ui/progress/protocol.py: ProgressSink protocol, opaque SubtaskID, and shared helpers."""

from __future__ import annotations

import re
from typing import Protocol


# Strip all Rich markup tags (e.g. "[dim]...[/dim]", "[bold]", "[LOSSY]") from
# messages before passing them through Text.from_markup(), which would otherwise
# render the tags literally.
_STRIP_MARKUP_RE = re.compile(r"\[[^\]]+\]")


class SubtaskID:
    """
    Opaque wrapper around a per-job bar identifier.

    Callers receive an instance from ``start_subtask`` and pass it back to
    ``finish_subtask``; they never see or construct the underlying integer ID,
    and they can never reach ``_job_tasks`` directly.
    """

    __slots__ = ("_id",)

    def __init__(self, _id: int) -> None:
        self._id: int = _id

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SubtaskID):
            return self._id == other._id
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return "SubtaskID(...)"


class ProgressSink(Protocol):
    """Typed protocol consumed by ``runner.run_all`` and ``scanner.scan_with_progress``."""

    def start_phase(self, name: str, total: int) -> None:
        """Begin a new phase (e.g. 'Scanning', 'Probing', 'Converting')."""
        ...

    def advance(self, amount: int = 1) -> None:
        """Advance the master bar by *amount* steps."""
        ...

    def start_subtask(self, name: str) -> SubtaskID:
        """Add an indeterminate per-job bar. Returns an opaque SubtaskID."""
        ...

    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        """Mark a per-job bar done and remove it from the display."""
        ...

    def log(self, message: str) -> None:
        """Append a message to the log area."""
        ...

    def stop(self) -> None:
        """Stop rendering. Safe to call without a prior ``start_phase`` call."""
        ...

    def stop_phase(self) -> None:
        """Flush pending state to the terminal, then clean up the Live renderer."""
        ...

    def set_activity(self, activity: str) -> None:
        """Set the current activity description (e.g., 'copying' or 'converting')."""
        ...

    def set_phase_label(self, label: str) -> None:
        """Update the master bar's phase label without restarting the phase.

        Used when one phase (e.g. ``Probing``) internally transitions
        between sub-stages (Extension -> Folder -> Mutagen) and the
        bar should keep advancing but show the current tier.
        """
        ...

    def log_verify_result(self, infile: str, status: str, reason: str | None,
                         fmt: str | None, duration_s: float | None) -> None:
        """Log a post-write verify result: 'Okay' or 'Not - <reason>'."""
        ...
