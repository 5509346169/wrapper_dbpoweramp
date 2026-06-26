"""ui/progress/rich_sink.py: RichProgressSink — concrete ProgressSink backed by rich.live.Live."""

from __future__ import annotations

import sys
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from src.ui.progress.protocol import SubtaskID, _STRIP_MARKUP_RE
from src.ui.progress.renderer import _ProgressRenderer


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

        # Force terminal is OFF: PowerShell on Windows does not reliably
        # respond to the cursor-position escape codes Rich's Live relies on,
        # and forcing ``force_terminal=True`` caused Live's refresh thread to
        # block indefinitely. With autodetect, Rich falls back to plain output
        # when stdout isn't a real terminal (piped, captured, etc.).
        self._console = Console(
            force_terminal=False,
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
        """Rebuild the layout and push a refresh to the Live display.

        Wrapped in a broad except: a Rich console error or terminal quirk
        must not crash the probe loop. Errors here are silently dropped so
        the actual work continues.
        """
        if self._live is None:
            return
        try:
            self._live.update(self._make_renderable())
        except Exception:
            pass

    def _make_renderable(self) -> Group:
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
            refresh_per_second=4,
            transient=False,
            screen=False,
        )
        # __enter__ can block on terminal probes; wrap defensively so a
        # terminal quirk never freezes the probe loop.
        try:
            self._live.__enter__()
        except Exception:
            self._live = None
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
        """Set the current activity description (e.g., 'copying' or 'converting')."""
        if self._renderer is None:
            return
        self._renderer.set_activity(activity)
        self._refresh()

    def log_file(self, message: str) -> None:
        """Append a file-level message, stripping any embedded Rich markup to avoid double-processing."""
        stripped = _STRIP_MARKUP_RE.sub("", message)
        self.log(stripped)

    def log_phase(self, name: str) -> None:
        """Set the phase name and log a phase header."""
        if self._renderer is not None:
            self._renderer.set_phase_name(name)
        self.log(f"[{name}]")
