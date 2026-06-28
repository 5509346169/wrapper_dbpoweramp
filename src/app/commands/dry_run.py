"""commands/dry_run.py: --dry-run command — build and print the job list without converting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.context import AppContext


def run(ctx: "AppContext") -> int:
    """Print the job list without executing any conversions."""
    from src.app.pipeline.jobs import build_jobs

    jobs = build_jobs([], ctx)

    phases = []
    if ctx.execution_mode.value == "phased":
        from src.app.pipeline.phases import run_jobs_by_phase
        phases = run_jobs_by_phase(jobs, ctx)
        print("Dry run — jobs that would be executed:")
        print()
        total_phases = len(phases)
        for i, (phase_label, batch) in enumerate(phases, 1):
            print(f"Phase {i}/{total_phases} — {phase_label} ({len(batch)} job(s))")
            for job in batch:
                lossy_marker = " [LOSSY]" if job.is_lossy_source else ""
                print(f"  {job.infile} -> {job.outfile}  [{job.job_type}]{lossy_marker}")
                if job.reason:
                    print(f"    reason: {job.reason}")
    else:
        phases = [("convert", jobs)]
        print("Dry run — jobs that would be executed:")
        print()
        for job in jobs:
            lossy_marker = " [LOSSY]" if job.is_lossy_source else ""
            print(f"  {job.infile} -> {job.outfile}  [{job.job_type}]{lossy_marker}")
            if job.reason:
                print(f"    reason: {job.reason}")

    print()
    print(f"Total: {len(jobs)} job(s)")
    return 0
