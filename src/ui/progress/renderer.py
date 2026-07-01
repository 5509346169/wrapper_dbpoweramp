"""ui/progress/renderer.py: Self-contained progress-bar renderer for RichProgressSink."""

from __future__ import annotations

import time as _time

from rich.console import Console
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

    Each row is a single ``Text`` of fixed total width, so the Live display
    never wraps and never gets clipped by ``Table.grid``'s column-width
    truncation marks. The width is recomputed every render from
    ``console.width`` so the description cell shrinks on narrow terminals and
    grows on wide ones instead of overflowing.

    Layout (single line per row):

        [bold]Converting[/] [bold cyan]29/359[/] [dim](330 left)[/]  [bar] [pct] [eta] [size]
        [dim]1.01. Track name                     [/][indeterminate bar] --- ...
    """

    BAR_WIDTH = 18

    # Widths of the fixed-width columns on the master row. The description
    # cell absorbs whatever slack remains after subtracting these + 4 padding
    # spaces (one between each of the 5 cells) from the console width.
    _PCT_WIDTH = 6     # "  83%" right-aligned
    _ETA_WIDTH = 11    # "  ETA: 0:32" or "  ETA: done"
    _SIZE_WIDTH = 9    # "858.0 GiB" right-aligned; column omitted when no size

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
        self._demoted: int = 0
        self._kept: int = 0

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

    def counters(self, demoted: int = 0, kept: int = 0) -> None:
        """Update the running per-decision counters shown next to the bar.

        The preverify phase uses this to make demote/keep totals visible as
        the bar advances, instead of waiting for the final summary log.
        """
        self._demoted = demoted
        self._kept = kept

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------

    def _desc_width(self) -> int:
        """Available description column width given the current console width.

        Subtracts the fixed columns (bar + pct + eta + size when present) and
        4 inter-cell padding spaces from the console width, then clamps to a
        reasonable minimum so the description is always readable.
        """
        width = self._console.width or 80
        fixed = self.BAR_WIDTH + self._PCT_WIDTH + self._ETA_WIDTH
        if self._total_bytes is not None:
            fixed += self._SIZE_WIDTH
        # 4 single-space gutters between the 5 cells (4 cells when size is hidden).
        gutters = 4 if self._total_bytes is not None else 3
        desc = width - fixed - gutters
        # Keep at least 20 chars for the phase label so we don't truncate it
        # into something unreadable on the very narrowest terminals.
        return max(20, min(desc, 60))

    def _build_description(self, desc_w: int) -> str:
        """Plain-text description cell content (no markup), width-aware.

        Builds the description from most-important to least-important segments
        (phase name, counts, optional activity, optional counters) and only
        includes a segment when it fits in ``desc_w`` chars. Truncates
        gracefully with a clean right-trim (no ``…`` markers) so column
        widths stay predictable and Live redraws cleanly.
        """
        remaining = max(0, self._total - self._master_done)
        left_label = "done" if remaining == 0 else f"{remaining} left"

        # Required: always present, in priority order.
        required = [
            self._phase_name,
            f"{self._master_done}/{self._total}",
            left_label,
        ]
        # Optional: appended after required if there is still room.
        optional: list[str] = []
        # Only show the activity indicator when it actually adds information
        # beyond what the phase name already conveys.  Otherwise the master
        # row becomes noisy: e.g. phase "Converting" + activity "convert"
        # renders as "Converting 0/359 359 left (convert)".
        if self._activity and self._activity.lower() not in self._phase_name.lower():
            optional.append(f"({self._activity})")
        if (self._demoted + self._kept) > 0:
            optional.append(f"↑{self._demoted} demote")
            optional.append(f"✓{self._kept} kept")

        segments = list(required)
        for opt in optional:
            candidate = " ".join(segments + [opt])
            if len(candidate) <= desc_w:
                segments.append(opt)
            # If it doesn't fit, drop it and stop trying — later opts are
            # even less important.
            else:
                break

        text = " ".join(segments)
        return self._truncate(text, desc_w)

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        """Right-trim ``text`` to ``width`` characters without inserting ``…``.

        Truncation marks (``…``) interfere with column-width math and look
        ugly next to a progress bar. A clean right-trim is more honest.
        """
        if len(text) <= width:
            return text.ljust(width)
        return text[: max(0, width)].rstrip()

    # ------------------------------------------------------------------
    # renderable
    # ------------------------------------------------------------------

    def render(self) -> Text:
        """Build a single Text renderable: master row + per-job rows stacked.

        Using a single ``Text`` (with ``\\n`` separators) instead of a
        ``Group`` of multiple ``Text`` lines keeps Live's height tracking
        deterministic and avoids orphan-cursor bugs on redraw.
        """
        if self._start_time is None:
            self._start_time = _time.monotonic()
        elapsed_now = _time.monotonic() - self._start_time

        desc_w = self._desc_width()
        desc = self._build_description(desc_w)

        # Master row — assembled as styled append() calls so each fragment keeps
        # its own color even when we right-pad with spaces.
        line = Text()
        line.append(desc, style="cyan")
        line.append(" ", style="default")
        bar_str = self._render_bar(self._master_done, self._total)
        line.append(bar_str, style="bar.complete")
        line.append(" ", style="default")
        line.append(self._pct(self._master_done, self._total).rjust(self._PCT_WIDTH), style="yellow")
        line.append(" ", style="default")
        line.append(self._eta_str(elapsed_now, self._master_done, self._total).ljust(self._ETA_WIDTH), style="magenta")
        if self._total_bytes is not None:
            line.append(" ", style="default")
            line.append(self._format_bytes(self._total_bytes).rjust(self._SIZE_WIDTH), style="blue")

        # Per-job rows — each on its own line.
        for bar in self._bars.values():
            line.append("\n")
            line.append(self._truncate(bar.description, desc_w), style="dim")
            line.append(" ", style="default")
            line.append(self._render_bar_indeterminate(), style="cyan")
            line.append(" ", style="default")
            line.append("---".rjust(self._PCT_WIDTH), style="dim")
            line.append(" ", style="default")
            line.append("...".ljust(self._ETA_WIDTH), style="dim")
            if self._total_bytes is not None:
                line.append(" ", style="default")
                line.append("".rjust(self._SIZE_WIDTH), style="dim")

        return line

    # ------------------------------------------------------------------
    # bar primitives
    # ------------------------------------------------------------------

    def _render_bar(self, done: int, total: int) -> str:
        """Return the filled-bar characters (no style; caller applies styling)."""
        if total <= 0:
            return " " * self.BAR_WIDTH
        pct = min(done / total, 1.0)
        filled = int(pct * self.BAR_WIDTH)
        return "█" * filled + "░" * (self.BAR_WIDTH - filled)

    def _render_bar_indeterminate(self) -> str:
        """Return the indeterminate-bar characters."""
        return "▰" * (self.BAR_WIDTH // 2) + "▱" * (self.BAR_WIDTH - self.BAR_WIDTH // 2)

    @staticmethod
    def _pct(done: int, total: int) -> str:
        if total <= 0:
            return "0%"
        return f"{min(done * 100 // total, 100)}%"

    @staticmethod
    def _eta_str(elapsed: float, done: int, total: int) -> str:
        if done <= 0 or elapsed <= 0:
            return "ETA: --:--"
        if done >= total and total > 0:
            return "ETA: done  "
        rate = done / elapsed
        remaining = total - done
        seconds = int(remaining / rate) if rate > 0 else 0
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"ETA: {h}:{m:02d}:{s:02d}"
        return f"ETA: {m}:{s:02d}  "

    @staticmethod
    def _format_bytes(num_bytes: int | None) -> str:
        if num_bytes is None:
            return ""
        if num_bytes >= 1 << 30:
            return f"{num_bytes / (1 << 30):.1f}G"
        if num_bytes >= 1 << 20:
            return f"{num_bytes / (1 << 20):.1f}M"
        if num_bytes >= 1 << 10:
            return f"{num_bytes / (1 << 10):.1f}K"
        return f"{num_bytes}B"