"""app/pipeline/jobs.py: Build ConversionJob list from index rows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.index.builder import IndexRow
from src.models.types import ConversionJob, LossyAction, PresetConfig

if TYPE_CHECKING:
    from src.app.context import AppContext


def build_jobs(
    source_rows: list["IndexRow"],
    ctx: "AppContext",
) -> list[ConversionJob]:
    """Build the ConversionJob list from index rows.

    Applies the lossy gate: if lossy files are found and no lossy_action is set,
    raises SystemExit(1) with an actionable message.

    Args:
        source_rows: The rows from the index (either from enrich phase or from index DB).
        ctx: The application context.

    Returns:
        A list of ConversionJob objects.
    """
    def _row_to_job(row: "IndexRow") -> ConversionJob:
        is_lossy_val = row.is_lossy
        if ctx.args.no_lossy_check:
            reason = None
        elif is_lossy_val:
            if ctx.args.lossy_action is None:
                reason = "lossy source, action=abort"
            elif ctx.args.lossy_action == "leave":
                reason = "lossy source, action=leave"
            elif ctx.args.lossy_action == "copy":
                reason = "lossy source, action=copy"
            else:
                reason = "lossy source, action=convert"
        else:
            reason = None
        return ConversionJob(
            infile=Path(row.source_path),
            outfile=Path(row.dest_path),
            preset=ctx.preset,
            job_type=row.job_type,
            is_lossy_source=is_lossy_val,
            reason=reason,
        )

    return [_row_to_job(r) for r in source_rows]


def check_lossy_gate(lossy_count: int, ctx: "AppContext") -> None:
    """Raise SystemExit(1) if lossy files found but no action specified."""
    import sys

    if (
        lossy_count > 0
        and ctx.args.lossy_action is None
        and not ctx.args.no_lossy_check
    ):
        print()
        print("Lossy source files found. You must specify --lossy-action to proceed.")
        print(f"Found {lossy_count} lossy file(s):")
        print()
        print("Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert")
        sys.exit(1)
