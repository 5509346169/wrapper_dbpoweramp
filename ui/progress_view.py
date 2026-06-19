"""ui/progress_view.py: Thin extraction of the original script's rich Live/Layout/Progress/Panel wiring."""

from __future__ import annotations

import sys
from collections import deque
from typing import TYPE_CHECKING

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

if TYPE_CHECKING:
    from rich.progress import TaskID


class ProgressView:
    """
    A thin wrapper around rich.live.Live that manages a two-panel layout:
    - A progress bar on top.
    - An optional verbose log stream panel below (when verbose=True).

    The class exposes `progress` (rich.progress.Progress) and `master_task`
    (rich.progress.TaskID) so the Execution Runner can update progress after
    each job.

    Example
    -------
    >>> with ProgressView(total=5, verbose=True) as view:
    ...     view.update_log(["Starting conversion..."])
    ...     view.progress.update(view.master_task, advance=1)
    """

    def __init__(self, total: int, verbose: bool = False) -> None:
        """
        Initialize the ProgressView.

        Args:
            total: The total number of items (files) to process.
            verbose: If True, render a two-panel layout with a log stream
                panel below the progress bar. If False, render only the
                progress bar.
        """
        self._total = total
        self._verbose = verbose
        self._live: Live | None = None
        self._started = False
        self._console = Console(file=sys.stdout)

        # Progress bar instance — exposed for the Execution Runner to update.
        self.progress: Progress = Progress(
            TextColumn("[bold blue]{task.description}[/bold blue]"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=self._console,
        )

        # Master task ID — exposed so the runner can call progress.update(master_task, advance=1).
        self.master_task: TaskID = self.progress.add_task("[green]Processing...", total=total)

        # Deque of recent log lines for the verbose panel.
        self._log_lines: deque[str] = deque(maxlen=10)

    def start(self) -> "ProgressView":
        """
        Start the rich.live.Live rendering context.

        Returns:
            self, so the instance can be used as a context manager.

        Raises:
            RuntimeError: If start() is called more than once without stop().
        """
        if self._started:
            raise RuntimeError("ProgressView.start() called twice")

        if self._verbose:
            layout = self._build_layout()
        else:
            layout = self.progress

        self._live = Live(
            layout,
            console=self._console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.__enter__()
        self._started = True
        return self

    def _build_layout(self) -> Layout:
        """Build the two-panel layout (progress bar + verbose log panel)."""
        layout = Layout()

        progress_panel = Panel(
            self.progress,
            title="Progress",
            border_style="green",
            padding=(0, 1),
        )

        verbose_panel = Panel(
            "\n".join(self._log_lines) if self._log_lines else "[dim]Waiting for output...[/dim]",
            title="Verbose Log",
            border_style="cyan",
            padding=(0, 1),
        )

        layout.split_column(progress_panel, verbose_panel)
        return layout

    def update_log(self, lines: list[str]) -> None:
        """
        Update the verbose log panel with the most recent lines.

        This method is a no-op when verbose=False.

        Args:
            lines: New log lines to append. The internal deque keeps only the
                most recent N lines (N=10).
        """
        if not self._verbose:
            return

        self._log_lines.extend(lines)

        if self._started and self._live is not None:
            verbose_panel = Panel(
                "\n".join(self._log_lines) if self._log_lines else "[dim]Waiting for output...[/dim]",
                title="Verbose Log",
                border_style="cyan",
                padding=(0, 1),
            )
            progress_panel = Panel(
                self.progress,
                title="Progress",
                border_style="green",
                padding=(0, 1),
            )
            layout = Layout()
            layout.split_column(progress_panel, verbose_panel)
            self._live.update(layout)

    def stop(self) -> None:
        """
        Stop the rich.live.Live rendering context.

        This method is safe to call multiple times (idempotent after the
        first call).
        """
        if self._started and self._live is not None:
            self._live.__exit__(None, None, None)
            self._live = None
            self._started = False

    def __enter__(self) -> "ProgressView":
        """Enter the context manager, starting the Live rendering."""
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager, stopping the Live rendering."""
        self.stop()
