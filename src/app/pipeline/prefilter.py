"""app/pipeline/prefilter.py: Pre-filter jobs — skip check + optional pre-verify demotion gate."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.audio.integrity import VerifyStatus, verify_file
from src.history.db import ConversionDB
from src.models.types import ConversionJob

if TYPE_CHECKING:
    from src.app.context import AppContext


def prefilter_jobs(
    jobs: list[ConversionJob],
    ctx: "AppContext",
) -> tuple[list[ConversionJob], list[ConversionJob]]:
    """Classify jobs into skipped vs pending using the history DB.

    Applies the pre-verify gate when --verify-skip is set: skip candidates whose
    on-disk output fails a full-frame decode are demoted to pending (forced reconvert).

    Args:
        jobs: All jobs from the build step.
        ctx: The application context.

    Returns:
        A tuple of (pending_jobs, skipped_jobs).
    """
    pending_jobs: list[ConversionJob] = []
    skipped_jobs: list[ConversionJob] = []

    if not ctx.args.force:
        db = ConversionDB(ctx.db_path)
        try:
            for job in jobs:
                dest_exists = job.outfile.exists()
                dest_size = job.outfile.stat().st_size if dest_exists else None

                if db.should_skip(
                    str(job.infile), str(job.outfile),
                    job_type=job.job_type,
                    dest_file_exists=dest_exists,
                    dest_file_size=dest_size,
                ):
                    # ── pre-verify gate (skip candidates only) ─────────────────
                    if ctx.args.verify_skip and dest_exists and job.job_type in ("convert", "copy"):
                        pre = verify_file(job.outfile)
                        if pre.status is VerifyStatus.NOT_OK:
                            # Corrupt output → demote to pending for reconvert.
                            pending_jobs.append(job)
                        else:
                            # OK or UNSUPPORTED → trust the existing output.
                            skipped_jobs.append(job)
                    else:
                        skipped_jobs.append(job)
                else:
                    pending_jobs.append(job)
        finally:
            db.close()
    else:
        pending_jobs = list(jobs)

    return pending_jobs, skipped_jobs
