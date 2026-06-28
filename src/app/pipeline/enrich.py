"""app/pipeline/enrich.py: Enrich phase — lossy probe + output path + job type."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint
from src.index.builder import IndexBuilder
from src.jobs.builder import enrich_index_rows_streaming
from src.models.types import IndexRow, LossyAction, PresetConfig

if TYPE_CHECKING:
    from src.app.context import AppContext
    from src.ui.progress_view import ProgressSink


def enrich(
    scan_rows: list["IndexRow"],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    ctx: "AppContext",
    progress: "ProgressSink | None" = None,
    index_builder: "IndexBuilder | None" = None,
) -> tuple[list["IndexRow"], list[str]]:
    """Run the enrich phase: lossy probe + output path + job type.

    Keeps the progress bar alive — scanning has finished and probing is
    the expensive step. Rows are written to the index DB as each probe
    result arrives, so the DB is a real-time snapshot rather than a
    deferred write.

    Args:
        scan_rows: The rows from the scan phase.
        input_root: Root of the input path (for relative-path math).
        source_root: Optional explicit source root.
        output_root: Output directory root.
        ctx: The application context.
        progress: Optional progress sink.
        index_builder: Optional pre-opened IndexBuilder.

    Returns:
        A tuple of (enriched rows, list of lossy file paths).
    """
    lossy_action: LossyAction | None = None
    if ctx.args.lossy_action is not None:
        lossy_action = LossyAction(ctx.args.lossy_action)

    lossy_files_found = enrich_index_rows_streaming(
        scan_rows=scan_rows,
        input_root=input_root,
        source_root=source_root,
        output_root=output_root,
        preset=ctx.preset,
        lossy_action=lossy_action,
        no_lossy_check=ctx.args.no_lossy_check,
        probe_workers=ctx.settings.execution.probe_workers,
        progress=progress,
        index_builder=index_builder,
    )

    return scan_rows, lossy_files_found
