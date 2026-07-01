"""app/pipeline/prefilter.py: Pre-filter jobs — skip check + optional pre-verify demotion gate."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.audio.integrity import VerifyStatus, verify_file
from src.history.db import ConversionDB
from src.models.types import ConversionJob
from src.ui.progress.null_sink import NullProgressSink
from src.ui.progress.protocol import ProgressSink

if TYPE_CHECKING:
    from src.app.context import AppContext


def prefilter_jobs(
    jobs: list[ConversionJob],
    ctx: "AppContext",
    sink: ProgressSink | None = None,
) -> tuple[list[ConversionJob], list[ConversionJob]]:
    """Classify jobs into skipped vs pending using the history DB.

    Applies the pre-verify gate when --verify-skip is set: skip candidates whose
    on-disk output fails a full-frame decode are demoted to pending (forced reconvert).

    When ``ctx.failed_only`` is True, only jobs whose latest history row is
    FAILED remain pending; everything else is skipped. This takes precedence
    over the resume-cache check (so a previously-FAILED-but-now-skippable job
    is still retried) and over ``--force``'s semantics (which ``validate_args``
    makes mutually exclusive).

    Args:
        jobs: All jobs from the build step.
        ctx: The application context.
        sink: Optional ProgressSink for reporting pre-verify progress. Defaults
            to ``NullProgressSink()`` (no-op) so callers that don't care about
            progress keep working unchanged.

    Returns:
        A tuple of (pending_jobs, skipped_jobs).
    """
    pending_jobs: list[ConversionJob] = []
    skipped_jobs: list[ConversionJob] = []

    if sink is None:
        sink = NullProgressSink()

    # ── --failed-only branch (runs before the normal resume-cache check) ──
    # The user's instruction is explicit: convert only files whose latest
    # history row is FAILED, leave everything else alone. We bulk-load the
    # failed triples once and split the jobs in O(N) without touching the
    # skip-cache logic at all.
    #
    # We consult ``ctx.failed_only`` (the resolved AppContext bool) rather
    # than ``ctx.args.failed_only`` directly. ``build_context`` collapses the
    # argparse ``None``-default to ``False`` there; the existing prefilter
    # tests build a MagicMock for ``args`` whose unset attribute is also a
    # MagicMock (truthy), which would otherwise route every test through
    # this branch.
    if getattr(ctx, "failed_only", False):
        sink.start_phase("Filtering to failed-only", total=len(jobs))
        try:
            db = ConversionDB(ctx.db_path)
            try:
                failed_set = db.failed_job_pairs(("convert", "copy"))
            finally:
                db.close()
            for job in jobs:
                key = (str(job.infile), str(job.outfile), job.job_type)
                if key in failed_set:
                    pending_jobs.append(job)
                else:
                    skipped_jobs.append(job)
            sink.log(
                f"[failed-only] {len(pending_jobs)} previously-failed job(s) "
                f"queued for retry, {len(skipped_jobs)} other file(s) skipped "
                f"(matched against latest history row only)."
            )
        finally:
            # Advance the bar even though there is no per-file work; the user
            # should still see a 100% complete "Filtering to failed-only" bar.
            for _ in range(len(jobs)):
                sink.advance()
            sink.stop_phase()
        return pending_jobs, skipped_jobs

    if not ctx.args.force:
        db = ConversionDB(ctx.db_path)
        try:
            # ── Pass 1: cheap DB-only skip check. Collect the skip candidates
            # that will actually need a verify_file() call so we can show an
            # accurate progress total before the slow decode phase starts.
            skip_candidates: list[ConversionJob] = []
            not_skip: list[ConversionJob] = []
            for job in jobs:
                dest_exists = job.outfile.exists()
                dest_size = job.outfile.stat().st_size if dest_exists else None

                if db.should_skip(
                    str(job.infile), str(job.outfile),
                    job_type=job.job_type,
                    dest_file_exists=dest_exists,
                    dest_file_size=dest_size,
                ):
                    # Pre-verify only applies to convert/copy outputs we can decode.
                    if ctx.args.verify_skip and dest_exists and job.job_type in ("convert", "copy"):
                        skip_candidates.append(job)
                    else:
                        skipped_jobs.append(job)
                else:
                    not_skip.append(job)

            # Non-skip jobs are immediately pending (no verification needed).
            pending_jobs.extend(not_skip)

            # ── Pass 2: verify_file() per skip candidate with a progress bar. ──
            if skip_candidates:
                if ctx.args.verify_skip:
                    phase_name = f"Pre-verifying {len(skip_candidates):,} files"
                else:
                    # Defensive: verify_skip can change between Pass 1 and Pass 2
                    # only via threading; if it did, fall back to the existing
                    # no-verify branch semantics.
                    phase_name = f"Filtering {len(skip_candidates):,} cached output(s)"
                sink.start_phase(phase_name, total=len(skip_candidates))
                sink.set_activity("verifying")
                demoted = 0
                kept = 0
                try:
                    for idx, job in enumerate(skip_candidates, start=1):
                        if ctx.args.verify_skip:
                            pre = verify_file(job.outfile)
                            if pre.status is VerifyStatus.NOT_OK:
                                pending_jobs.append(job)
                                demoted += 1
                                # Only log when something was actually demoted.
                                # Throttle the UI refresh to every 50 demotes to keep
                                # the bar responsive for large skip-candidate lists
                                # (25k+ files). Always log the final file.
                                is_last = (idx == len(skip_candidates))
                                if is_last or (demoted % 50 == 1):
                                    short_reason = (pre.reason or 'unknown').splitlines()[0][:60]
                                    sink.log_file(
                                        f"[preverify] demoted #{idx}/{len(skip_candidates)}: "
                                        f"{job.outfile.name} ({short_reason})"
                                    )
                            else:
                                skipped_jobs.append(job)
                                kept += 1
                        else:
                            skipped_jobs.append(job)
                            kept += 1
                        sink.advance()
                        # Update inline counters: every 50 advances for responsive
                        # telemetry without re-rendering on every single file.
                        if idx % 50 == 0:
                            sink.set_counters(demoted=demoted, kept=kept)
                finally:
                    sink.set_counters(demoted=demoted, kept=kept)
                    sink.log(
                        f"[preverify] {len(skip_candidates)} checked, "
                        f"{demoted} demoted for reconvert, "
                        f"{kept} kept (cache valid)"
                    )
                    sink.stop_phase()
            # else: nothing to verify — no phase was opened, so don't close one.
        finally:
            db.close()
    else:
        pending_jobs = list(jobs)

    return pending_jobs, skipped_jobs
