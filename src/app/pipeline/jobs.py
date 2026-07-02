"""app/pipeline/jobs.py: Build ConversionJob list from index rows."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.index.builder import IndexRow
from src.models.types import ConversionJob, LossyAction, PresetConfig

if TYPE_CHECKING:
    from src.app.context import AppContext
    from src.index.staging_cache import StagingCache


def build_jobs(
    source_rows: list["IndexRow"],
    ctx: "AppContext",
    staging_cache: "StagingCache | None" = None,
) -> list[ConversionJob]:
    """Build the ConversionJob list from index rows.

    Applies the lossy gate: if lossy files are found and no lossy_action is set,
    raises SystemExit(1) with an actionable message.

    When ``staging_cache`` is provided, upserts each job's md5sum →
    (source_path, dest_path, temp_path) mapping into the cache so the
    staging association is persisted for recovery in subsequent runs.

    Args:
        source_rows: The rows from the index (either from enrich phase or from index DB).
        ctx: The application context.
        staging_cache: Optional staging cache for persisting md5sum → temp path mappings.

    Returns:
        A list of ConversionJob objects.
    """
    from src.pathing.md5_staging import compute_md5sum

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

    jobs = [_row_to_job(r) for r in source_rows]

    # Populate the staging cache with md5sum → temp path mapping for each job.
    # This is done at build time so the cache is ready before any conversion runs.
    if staging_cache is not None:
        for job in jobs:
            if job.job_type != "convert":
                continue
            md5sum = compute_md5sum(job.infile)
            ext = job.outfile.suffix.lstrip(".")
            temp_filename = f"{md5sum}.md5hash.{ext}"
            tmp_root = Path("tmp") / "audio"
            temp_infile = str(tmp_root / "src" / temp_filename)
            temp_outfile = str(tmp_root / "dst" / temp_filename)
            try:
                staging_cache.upsert(
                    source_path=str(job.infile),
                    dest_path=str(job.outfile),
                    md5sum=md5sum,
                    temp_infile=temp_infile,
                    temp_outfile=temp_outfile,
                    temp_filename=temp_filename,
                )
            except Exception:
                # Non-fatal: cache write failures must not interrupt the job list.
                pass

    return jobs


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
