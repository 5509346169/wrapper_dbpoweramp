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
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

if TYPE_CHECKING:
    from rich.progress import TaskID


# Maximum number of per-job progress bars to show at once.
_MAX_VISIBLE_JOBS = 8


class ProgressView:
    """
    A thin wrapper around rich.live.Live that manages a two-panel layout:
    - A progress bar on top.
    - An optional verbose log stream panel below (when verbose=True).

    The class exposes `progress` (rich.progress.Progress) and `master_task`
    (rich.progress.TaskID) so the Execution Runner can update progress after
    each job.

    When workers > 1, per-job progress bars are rendered dynamically in the
    main progress panel. Each bar represents one active or recently completed
    job, allowing the user to see parallel progress across workers.

    Example
    -------
    >>> with ProgressView(total=5, workers=4, verbose=True) as view:
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
            workers: Number of parallel workers. When > 1, per-job progress
                bars are displayed alongside the master bar.
        """
        self._total = total
        self._verbose = verbose
        self._workers = workers
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

        # Per-job tasks: maps job infile name -> TaskID
        self._job_tasks: dict[str, TaskID] = {}

        # Queue of job names to show in the per-job bars (most recent first)
        self._visible_job_names: list[str] = []


    def _rebuild_progress_panel(self) -> None:
        """Rebuild the progress panel with per-job bars, updating the Live display."""
        self.progress.refresh()

    def add_job_task(self, infile_name: str) -> TaskID:
        """
        Add a per-job progress bar and return its TaskID.

        Args:
            infile_name: Short name of the input file (used as the task key).

        Returns:
            The TaskID for the newly added job bar.
        """
        # Limit concurrent bars to avoid terminal clutter.
        max_visible = min(self._workers, _MAX_VISIBLE_JOBS)

        # Evict the oldest entry if we're at capacity.
        if len(self._visible_job_names) >= max_visible:
            oldest = self._visible_job_names.pop(0)
            if oldest in self._job_tasks:
                self.progress.remove_task(self._job_tasks.pop(oldest))

        self._visible_job_names.append(infile_name)
        task = self.progress.add_task(
            infile_name,
            total=None,  # indeterminate spinner + bar
            start=True,
        )
        self._job_tasks[infile_name] = task
        return task

    def remove_job_task(self, infile_name: str, status: str) -> None:
        """
        Mark a per-job progress bar as complete and remove it from the display.

        Args:
            infile_name: Short name of the input file (task key).
            status: One of SUCCESS, SKIPPED, FAILED — used in the bar label.
        """
        if infile_name not in self._job_tasks:
            return

        task_id = self._job_tasks[infile_name]
        self.progress.update(task_id, completed=True, description=f"[dim]{infile_name}: {status}[/dim]")
        del self._job_tasks[infile_name]
        if infile_name in self._visible_job_names:
            self._visible_job_names.remove(infile_name)
        self._rebuild_progress_panel()

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
            self._rebuild_progress_panel()

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
