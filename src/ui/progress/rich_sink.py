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

    def _make_renderable(self) -> Text | Group:
        """Build the compact inline stack: bar row(s) + up to LOG_LINES log lines.

        The renderer emits a single ``Text`` with embedded newlines (one row
        per progress bar). Log lines are appended below that Text, separated
        by ``\\n`` so the whole block is one contiguous Text the Live
        redraws atomically. Falling back to a ``Group`` here would break the
        single-renderable contract that Live relies on for clean cursor
        positioning.
        """
        renderer = self._renderer
        if renderer is None:
            progress_text = Text("[dim]Idle[/dim]")
        else:
            progress_text = renderer.render()

        if not self._log_lines:
            return progress_text

        # Combine into a single Text with embedded newlines so Live sees one
        # renderable instead of a Group (which it tracks with separate
        # height bookkeeping per child).
        combined = Text()
        combined.append_text(progress_text)
        for msg in list(self._log_lines)[-self.LOG_LINES:]:
            combined.append("\n")
            combined.append("  ", style="default")
            combined.append_text(Text.from_markup(msg, style="dim"))
        return combined

    # ------------------------------------------------------------------
    # ProgressSink implementation
    # ------------------------------------------------------------------

    def start_phase(self, name: str, total: int) -> None:
        """Begin a new phase with a master progress bar.

        If a Live is already active from a previous phase, reuses it instead
        of creating a new one — this prevents terminal flicker and cursor
        repositioning between phases when the same sink is shared across
        scan → enrich → prefilter → convert.
        """
        if self._live is not None:
            # Reuse the existing Live: swap out the renderer (which carries
            # phase name, bar state, counters) and push the new renderable
            # so the next Live tick picks it up without flicker.
            self._renderer = _ProgressRenderer(
                total=total,
                total_bytes=self._total_bytes,
                console=self._console,
                phase_name=name,
            )
            self._last_phase_label = name
            self._live.update(self._make_renderable())
            self._live.refresh()
            self._refresh()
            return

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
        # Force a synchronous first render immediately so the bar appears on
        # screen before the first result arrives — eliminates the gap where the
        # terminal shows nothing until the refresh thread fires 50-100ms later.
        self._live.refresh()
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

    def log_convert_result(self, infile: str, outfile: str, encoder: str,
                          output_bytes: int | None, elapsed_s: float,
                          status: str, error_msg: str | None = None) -> None:
        """Log a conversion result with size and elapsed time to the log area."""
        import os as _os

        elapsed_str = f"{elapsed_s:.2f}s"
        if status == "SUCCESS":
            if output_bytes is not None:
                if output_bytes >= 1 << 30:
                    size_str = f"{output_bytes / (1 << 30):.1f} GiB"
                elif output_bytes >= 1 << 20:
                    size_str = f"{output_bytes / (1 << 20):.1f} MiB"
                elif output_bytes >= 1 << 10:
                    size_str = f"{output_bytes / (1 << 10):.1f} KiB"
                else:
                    size_str = f"{output_bytes} B"
            else:
                size_str = "?"
            self.log(
                f"[convert] SUCCESS  {elapsed_str}  {size_str:>9}  {encoder}  {outfile}"
            )
        else:
            reason = f"  ({error_msg})" if error_msg else ""
            self.log(
                f"[convert] FAILED   {elapsed_str}         -  {encoder}  {outfile}{reason}"
            )

    def set_phase_label(self, label: str) -> None:
        """Update the master bar's phase label without restarting the phase."""
        if self._renderer is None or label == self._last_phase_label:
            return
        self._last_phase_label = label
        self._renderer.set_phase_name(label)
        self._refresh()

    def set_counters(self, demoted: int = 0, kept: int = 0) -> None:
        """Update per-decision counters shown next to the master bar.

        The verify-skip preverify phase uses this to advertise demote/keep
        totals as the bar advances. Other sinks implement the same name as a
        no-op so the prefilter can call it without branching on sink type.

        Args:
            demoted: Number of skip candidates demoted to pending so far.
            kept: Number of skip candidates kept on the skip list so far.
        """
        if self._renderer is None:
            return
        self._renderer.counters(demoted=demoted, kept=kept)
        self._refresh()
