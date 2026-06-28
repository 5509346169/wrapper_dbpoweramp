"""ui/progress/rich_sink.py: RichProgressSink — concrete ProgressSink backed by rich.live.Live."""

from __future__ import annotations

import sys
import time
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

        # Force terminal ON so colors and bar styles render. PowerShell on
        # Windows 10+ supports VT100 escapes by default; on hosts that don't
        # (e.g. when stdout is redirected), Rich's autodetect still falls back
        # to plain output because ``is_terminal`` is consulted for the Live
        # cursor moves regardless of ``force_terminal``.
        self._console = Console(
            force_terminal=True,
            legacy_windows=False,
            file=sys.stdout,
        )
        self._live: Live | None = None
        self._renderer: _ProgressRenderer | None = None
        self._log_lines: deque[str] = deque(maxlen=30)
        self._last_phase_label: str = ""

        # Throttle state for _refresh(): we update the Live renderable at
        # most every _MIN_REFRESH_INTERVAL seconds. Rich's Live thread
        # already redraws at refresh_per_second; calling .update() per
        # advance() is wasted work when 26k files complete in seconds.
        self._MIN_REFRESH_INTERVAL = 0.05  # 50ms = up to 20 Hz
        self._last_refresh_ts: float = 0.0
        self._refresh_pending: bool = False

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _flush_sync(self) -> None:
        """Force a single synchronous render so the terminal shows the current state.

        After this returns, the Live is still alive — its stop() method (called
        by ``__exit__``) will call refresh() again before doing its cleanup,
        so the final committed state is preserved on screen.
        """
        if self._live is None:
            return
        self._live.update(self._make_renderable())
        self._live.refresh()

    def _refresh(self) -> None:
        """Push a refresh to the Live display, throttled to ~20Hz.

        Rich's Live runs its own refresh thread (refresh_per_second=10) so we
        do NOT call ``self._live.refresh()`` here — that would force a
        synchronous redraw on the calling thread for every state change.
        We only call ``self._live.update()``, which queues a new renderable
        for the Live thread to pick up at its next tick.

        Throttling skips redundant ``update()`` calls when state changes
        arrive faster than the display can render them.
        """
        if self._live is None:
            return
        now = time.monotonic()
        if now - self._last_refresh_ts >= self._MIN_REFRESH_INTERVAL:
            self._last_refresh_ts = now
            self._refresh_pending = False
            self._live.update(self._make_renderable())
        else:
            # Mark that state changed; the Live thread's tick (which calls
            # into the renderable) will reflect it on its next pass.
            self._refresh_pending = True

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
        # Stop any existing Live before creating a new one.  Without this,
        # successive calls to start_phase (scan -> probe -> convert) leave
        # orphaned Live instances whose cursors remain on the terminal,
        # causing flickering and overlapping output.
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None
        self._renderer = _ProgressRenderer(
            total=total,
            total_bytes=self._total_bytes,
            console=self._console,
            phase_name=name,
        )
        self._last_phase_label = name
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
        """Flush pending state, then cleanly tear down the Live display."""
        self._flush_sync()
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        self._renderer = None
        self._log_lines.clear()
        self._last_refresh_ts = 0.0
        self._refresh_pending = False

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

    def log_verify_result(self, infile: str, status: str, reason: str | None,
                         fmt: str | None, duration_s: float | None) -> None:
        """Log a post-write verify result: 'Okay' or 'Not - <reason>'."""
        if status == "OK":
            self.log(f"[verify] Okay")
        elif status == "UNSUPPORTED":
            self.log(f"[verify] Skipped - {reason or 'unsupported format'}")
        else:
            self.log(f"[verify] Not - {reason or 'unknown reason'}")

    def set_phase_label(self, label: str) -> None:
        """Update the master bar's phase label without restarting the phase."""
        if self._renderer is None or label == self._last_phase_label:
            return
        self._last_phase_label = label
        self._renderer.set_phase_name(label)
        self._refresh()
