"""ui/progress/renderer.py: Self-contained progress-bar renderer for RichProgressSink."""

from __future__ import annotations

import time as _time

from rich.console import Console
from rich.table import Table
from rich.text import Text


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
    # Cap visible bars so the total terminal line width stays within 80 chars.
    # Line layout:  "[dim]<desc26>[/] <bar18> [dim]---[/] [dim]...[/]\n"  =>  26+1+18+1+6+1+5  =  58  +  master row  =  ~70 chars
    # With 7 per-job rows the total is ~70 + 7*52 = 434 chars — well within 80 columns because Rich handles overflow.
    # Cap at BAR_WIDTH - BAR_WIDTH // 2 - 2 = 18 - 9 - 2 = 7 to leave room for the description column.
    MAX_VISIBLE_BARS = max(0, BAR_WIDTH - BAR_WIDTH // 2 - 2)

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
        # Enforce MAX_VISIBLE_BARS so we don't overflow the terminal width.
        while len(self._bars) > self.MAX_VISIBLE_BARS:
            oldest = min(self._bars)
            del self._bars[oldest]
        return bar_id

    def finish_bar(self, bar_id: int) -> None:
        """Mark a bar done and remove it."""
        self._bars.pop(bar_id, None)

    def render(self) -> Table:
        """Build the Table renderable for the current state."""
        table = Table.grid(padding=(0, 1), pad_edge=False)
        table.add_column(style="cyan", width=48)
        table.add_column(style="green", width=self.BAR_WIDTH)
        table.add_column(style="yellow", width=7)
        table.add_column(style="magenta", width=12)
        if self._total_bytes is not None:
            table.add_column(style="blue", width=11)

        master_bar = self._render_bar(self._master_done, self._total, "bold")
        if self._start_time is None:
            self._start_time = _time.monotonic()
        elapsed_now = _time.monotonic() - self._start_time
        if self._master_done >= self._total and self._total > 0:
            remaining_s = "  ETA: done"
        elif self._master_done == 0:
            remaining_s = "not started"
        else:
            remaining_s = self._eta_str(elapsed_now, self._master_done, self._total)
        bytes_str = self._format_bytes(self._total_bytes) if self._total_bytes else ""

        remaining_count = max(0, self._total - self._master_done)
        left_str = "done" if remaining_count == 0 else f"{remaining_count} left"

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
