"""ui/progress_view.py: ProgressSink Protocol, SubtaskID wrapper, and RichProgressSink implementation."""

from __future__ import annotations

import sys
from collections import deque
from typing import Protocol

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

import time as _time

if False:
    pass  # no TYPE_CHECKING imports needed


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


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
        """Clean up the current phase and reset the Live renderer to None."""
        ...

    def set_activity(self, activity: str) -> None:
        """Set the current activity description (e.g., 'copying', 'converting')."""
        ...


class NullProgressSink:
    """
    A no-op ProgressSink for verbose mode where output goes directly to stdout.

    All methods are no-ops - verbose output is printed directly via stream_callback.
    """

    def start_phase(self, name: str, total: int) -> None:
        pass

    def advance(self, amount: int = 1) -> None:
        pass

    def start_subtask(self, name: str) -> SubtaskID:
        return SubtaskID(-1)

    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def stop(self) -> None:
        pass

    def stop_phase(self) -> None:
        pass

    def set_activity(self, activity: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Internal progress-bar implementation
# ---------------------------------------------------------------------------


class _BarState:
    """Lightweight mutable state for one progress bar managed by RichProgressSink."""

    __slots__ = ("description", "done", "total")

    def __init__(self, description: str, total: int | None) -> None:
        self.description: str = description
        self.done: int = 0
        self.total: int | None = total


class _ProgressRenderer:
    """
    Self-contained progress-bar renderer.

    Replaces rich.progress.Progress so that the single rich.live.Live instance
    in RichProgressSink is the only Live context active.

    Master bar columns:  description | bar | pct | ETA | size (gated)
    Per-job bars:        indeterminate (spinning animation, no percentage).
    """

    BAR_WIDTH = 18

    def __init__(
        self,
        total: int,
        total_bytes: int | None,
        console: Console,
        phase_name: str = "Phase",
    ) -> None:
        self._total = total
        self._total_bytes = total_bytes
        self._console = console
        self._master_done: int = 0
        self._bars: dict[int, _BarState] = {}
        self._next_id: int = 0
        self._start_time: float | None = None
        self._phase_name = phase_name
        self._activity: str = ""

    def set_phase_name(self, name: str) -> None:
        self._phase_name = name

    def set_activity(self, activity: str) -> None:
        """Update the activity indicator (e.g., 'copying' or 'converting')."""
        self._activity = activity

    def add_bar(self, description: str, total: int | None = None) -> int:
        """Add a new bar; returns the internal integer ID."""
        bar_id = self._next_id
        self._next_id += 1
        self._bars[bar_id] = _BarState(description, total)
        return bar_id

    def finish_bar(self, bar_id: int) -> None:
        """Mark a bar done and remove it."""
        self._bars.pop(bar_id, None)

    def render(self) -> Table:
        """Build the Table renderable for the current state."""
        table = Table.grid(padding=(0, 1), pad_edge=False)
        table.add_column(style="cyan", width=36)
        table.add_column(style="green", width=self.BAR_WIDTH)
        table.add_column(style="yellow", width=7)
        table.add_column(style="magenta", width=12)
        if self._total_bytes is not None:
            table.add_column(style="blue", width=11)

        master_bar = self._render_bar(self._master_done, self._total, "bold")
        if self._start_time is None:
            self._start_time = _time.monotonic()
        elapsed_now = _time.monotonic() - self._start_time
        remaining_s = (
            "not started"
            if self._master_done == 0
            else self._eta_str(elapsed_now, self._master_done, self._total)
        )
        bytes_str = self._format_bytes(self._total_bytes) if self._total_bytes else ""

        remaining_count = max(0, self._total - self._master_done)
        left_str = f"{remaining_count} left"

        activity_str = f" [dim]({self._activity})[/dim]" if self._activity else ""

        row: list[Text | str] = [
            f"[bold]{self._phase_name}[/] [bold cyan]{self._master_done}/{self._total}[/] [dim]({left_str})[/dim]{activity_str}",
            master_bar,
            f"{self._pct(self._master_done, self._total):>6}",
            remaining_s,
        ]
        if self._total_bytes is not None:
            row.append(bytes_str)
        table.add_row(*row)

        for bar_id, bar in self._bars.items():
            job_bar = self._render_bar_indeterminate()
            table.add_row(
                f"[dim]{bar.description[:26]}[/]",
                job_bar,
                "[dim]---[/]",
                "[dim]...[/]",
            )

        return table

    def _render_bar(self, done: int, total: int, extra_style: str = "") -> Text:
        """Render a filled progress bar."""
        if total <= 0:
            return Text(" " * self.BAR_WIDTH)
        pct = min(done / total, 1.0)
        filled = int(pct * self.BAR_WIDTH)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        style = f"{extra_style} bar.complete" if extra_style else "bar.complete"
        return Text(bar, style=style)

    def _render_bar_indeterminate(self) -> Text:
        """Render an indeterminate bar."""
        bar = "▰" * (self.BAR_WIDTH // 2) + "▱" * (self.BAR_WIDTH - self.BAR_WIDTH // 2)
        return Text(bar, style="cyan")

    @staticmethod
    def _pct(done: int, total: int) -> str:
        if total <= 0:
            return "  0%"
        return f"{min(done * 100 // total, 100):>3}%"

    @staticmethod
    def _eta_str(elapsed: float, done: int, total: int) -> str:
        if done <= 0 or elapsed <= 0:
            return "  ETA: --:--"
        rate = done / elapsed
        remaining = total - done
        seconds = int(remaining / rate) if rate > 0 else 0
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"  ETA: {h}:{m:02d}:{s:02d}"
        return f"  ETA: {m}:{s:02d}"

    @staticmethod
    def _format_bytes(num_bytes: int | None) -> str:
        if num_bytes is None:
            return ""
        if num_bytes >= 1 << 30:
            return f"{num_bytes / (1 << 30):.1f} GiB"
        if num_bytes >= 1 << 20:
            return f"{num_bytes / (1 << 20):.1f} MiB"
        if num_bytes >= 1 << 10:
            return f"{num_bytes / (1 << 10):.1f} KiB"
        return f"{num_bytes} B"


# ---------------------------------------------------------------------------
# Concrete ProgressSink implementation
# ---------------------------------------------------------------------------


class RichProgressSink:
    """
    Concrete ``ProgressSink`` backed by ``rich.live.Live``.

    Owns a single ``Live`` context and a single refresh path.  Every public
    method call refreshes the display.

    Compact layout (no panels, no borders):
      - Line 1:  [PhaseName N files]  ████████░░░░░░░░  83%  ETA 0:32  1.2 GiB
      - Lines 2+: [dim]log message 1[/dim]
                   [dim]log message 2[/dim]
                   ...
    """

    LOG_LINES = 3

    def __init__(
        self,
        total_files: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        self._total_files: int | None = total_files
        self._total_bytes: int | None = total_bytes

        self._console = Console(
            force_terminal=True,
            legacy_windows=False,
            file=sys.stdout,
        )
        self._live: Live | None = None
        self._renderer: _ProgressRenderer | None = None
        self._log_lines: deque[str] = deque(maxlen=30)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Rebuild the layout and push a refresh to the Live display."""
        if self._live is None:
            return
        self._live.update(self._make_renderable())
        self._live.refresh()

    def _make_renderable(self) -> Columns:
        """Build the compact inline stack: bar row + up to LOG_LINES log lines."""
        renderer = self._renderer
        if renderer is None:
            progress_renderable = Text("[dim]Idle[/dim]")
        else:
            progress_renderable = renderer.render()

        lines: list[Text] = [progress_renderable]

        if self._log_lines:
            for msg in list(self._log_lines)[-self.LOG_LINES:]:
                lines.append(Text.from_markup(f"[dim]  {msg}[/dim]"))

        return Group(*lines)

    # ------------------------------------------------------------------
    # ProgressSink implementation
    # ------------------------------------------------------------------

    def start_phase(self, name: str, total: int) -> None:
        """Begin a new phase with a master progress bar."""
        self._renderer = _ProgressRenderer(
            total=total,
            total_bytes=self._total_bytes,
            console=self._console,
            phase_name=name,
        )
        self._live = Live(
            self._make_renderable(),
            console=self._console,
            refresh_per_second=10,
            transient=False,
            screen=False,
        )
        self._live.__enter__()
        self._refresh()

    def advance(self, amount: int = 1) -> None:
        """Advance the master bar and refresh the display."""
        if self._renderer is None:
            return
        self._renderer._master_done += amount  # type: ignore[attr-defined]
        self._refresh()

    def start_subtask(self, name: str) -> SubtaskID:
        """Add an indeterminate per-job bar. Returns an opaque SubtaskID."""
        if self._renderer is None:
            return SubtaskID(-1)
        bar_id = self._renderer.add_bar(name)
        self._refresh()
        return SubtaskID(bar_id)

    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        """Mark a per-job bar done and remove it from the display."""
        if self._renderer is None:
            return
        self._renderer.finish_bar(bar_id=subtask_id._id)
        self._refresh()

    def log(self, message: str) -> None:
        """Append a message to the log area."""
        self._log_lines.append(message)
        self._refresh()

    def stop(self) -> None:
        """
        Stop rendering. Safe to call without a prior ``start_phase`` call.
        """
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None
        self._renderer = None

    def stop_phase(self) -> None:
        """Clean up the current Live instance and reset the renderer."""
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None
        self._renderer = None

    def set_activity(self, activity: str) -> None:
        """Set the current activity description (e.g., 'copying', 'converting')."""
        if self._renderer is None:
            return
        self._renderer.set_activity(activity)
        self._refresh()
