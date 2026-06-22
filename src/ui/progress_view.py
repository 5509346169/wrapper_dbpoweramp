"""ui/progress_view.py: Thin extraction of the original script's rich Live/Layout/Progress/Panel wiring."""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
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

    When workers > 1, each worker creates and manages its own per-job bar:
    bar is added when the worker starts, set to completed=1 on finish, and
    removed immediately. A background polling loop keeps the Live display
    refreshed while jobs are running. This mirrors the original script's
    pattern exactly.

    Example
    -------
    >>> with ProgressView(total=5, verbose=True) as view:
    ...     view.update_log(["Starting conversion..."])
    ...     view.progress.update(view.master_task, advance=1)
    """

    def __init__(
        self,
        total: int,
        verbose: bool = False,
        workers: int = 1,
    ) -> None:
        """
        Initialize the ProgressView.

        Args:
            total: The total number of items (files) to process.
            verbose: If True, render a two-panel layout with a log stream
                panel below the progress bar. If False, render only the
                progress bar.
            workers: Number of parallel workers. When > 1, the Live display
                is polled at ~50ms intervals to keep per-job bars fresh.
        """
        self._total = total
        self._verbose = verbose
        self._workers = workers
        self._live: Live | None = None
        self._started = False
        self._console = Console(file=sys.stdout)

        self.progress: Progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=20),
            TaskProgressColumn(),
            console=self._console,
            transient=False,
            auto_refresh=False,
        )

        self.master_task: TaskID = self.progress.add_task(
            "[bold]Converting",
            total=total,
        )

        self._job_tasks: dict[str, TaskID] = {}

        self._log_lines: deque[str] = deque(maxlen=15)
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._layout: Layout | None = None

    def add_job_task(self, infile_name: str) -> TaskID:
        """
        Add an indeterminate per-job bar when a worker starts.

        Mirrors the original script: worker calls this at start, then
        calls remove_job_task() on completion.

        Args:
            infile_name: Short name of the input file.

        Returns:
            The TaskID for the newly added job bar.
        """
        task_id = self.progress.add_task(
            f"[cyan]{infile_name[:25]}[/]",
            total=None,
        )
        self._job_tasks[infile_name] = task_id
        return task_id

    def remove_job_task(self, task_id: TaskID) -> None:
        """
        Mark a per-job bar done and remove it from the display.

        Called by the worker on job completion.

        Args:
            task_id: The TaskID returned by add_job_task().
        """
        self.progress.update(task_id, completed=1)
        self.progress.remove_task(task_id)
        self._job_tasks = {k: v for k, v in self._job_tasks.items() if v != task_id}

    def update_log(self, lines: list[str]) -> None:
        """
        Append lines to the verbose log stream.

        Workers call this to push per-job output into the log panel.

        Args:
            lines: New log lines to append. The internal deque keeps only the
                most recent N lines (N=15).
        """
        self._log_lines.extend(lines)

    def _poll_loop(self) -> None:
        """Background thread: refresh the Live display every ~50ms while jobs run."""
        while not self._poll_stop.wait(0.05):
            if self._live is not None:
                self._live.refresh()
            time.sleep(0.05)

    def update_layout(self) -> None:
        """
        Refresh the Live display layout (used by the polling loop in main.py).

        Rebuilds the progress panel and verbose log panel from current state.
        """
        if self._live is not None and self._layout is not None:
            from rich.text import Text

            log_text = Text.from_markup("\n".join(self._log_lines)) if self._log_lines else Text("[dim]Waiting for output...[/dim]")
            self._layout["main"].update(
                Panel(self.progress, title="Progress", border_style="green")
            )
            self._layout["footer"].update(
                Panel(log_text, title="CoreConverter Live Verbose Stream", border_style="blue")
            )
            self._live.refresh()

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

        self.progress.start()
        self._started = True

        if self._workers > 1:
            layout = self._build_layout()
            self._layout = layout
            self._live = Live(
                layout,
                console=self._console,
                refresh_per_second=20,
                transient=False,
                screen=False,
            )
            self._live.__enter__()
            self._poll_stop.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
        elif self._verbose:
            layout = self._build_layout()
            self._layout = layout
            self._live = Live(
                layout,
                console=self._console,
                refresh_per_second=10,
                transient=False,
            )
            self._live.__enter__()
        else:
            self._live = None

        return self

    def _build_layout(self) -> Layout:
        """Build the two-panel layout (progress bar + verbose log panel)."""
        from rich.text import Text

        layout = Layout()
        layout.split(
            Layout(name="main", ratio=2),
            Layout(name="footer", ratio=1),
        )

        if not self._verbose:
            layout["footer"].visible = False

        log_text = Text.from_markup("\n".join(self._log_lines)) if self._log_lines else Text("[dim]Waiting for output...[/dim]")
        layout["main"].update(
            Panel(self.progress, title="Progress", border_style="green")
        )
        layout["footer"].update(
            Panel(log_text, title="CoreConverter Live Verbose Stream", border_style="blue")
        )
        return layout

    def stop(self) -> None:
        """
        Stop the rich.live.Live rendering context and poll thread.

        Safe to call multiple times.
        """
        if self._poll_stop is not None:
            self._poll_stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None
        if self._live is not None:
            self._live.__exit__(None, None, None)
            self._live = None
        self.progress.stop()
        self._started = False

    def __enter__(self) -> "ProgressView":
        """Enter the context manager, starting the Live rendering."""
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager, stopping the Live rendering."""
        self.stop()
