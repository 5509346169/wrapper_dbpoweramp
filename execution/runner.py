"""execution/runner.py: Execute ConversionJob lists using the configured backend."""

import shutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

from backends.base import ConversionBackend
from history.db import ConversionDB
from models.types import ConversionJob, JobResult, JobStatus
from sidecars.manager import copy_covers, copy_lyrics


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db: ConversionDB,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    progress: Any,
    master_task: Any,
) -> JobResult:
    """
    Execute a single ConversionJob.

    Args:
        job: The conversion job to execute.
        backend: The conversion backend to use.
        db: The history database for logging and resume checks.
        force: If True, skip resume checks and force re-processing.
        stream_callback: Optional callback for streaming output line-by-line.
        progress: Optional rich.progress.Progress instance.
        master_task: Optional rich.progress.TaskID for the master progress task.

    Returns:
        JobResult with status SUCCESS, SKIPPED, or FAILED.
    """
    if job.job_type == "skip":
        return JobResult(
            job=job,
            status="SKIPPED",
            error_msg="lossy, leave",
        )

    if job.job_type == "copy":
        try:
            job.outfile.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(job.infile, job.outfile)
        except Exception as e:
            return JobResult(
                job=job,
                status="FAILED",
                error_msg=str(e),
            )

        copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
        copy_covers(job.infile, job.outfile, job.preset.covers)

        db.log_conversion(
            source=str(job.infile),
            dest=str(job.outfile),
            job_type=job.job_type,
            command=None,
            status="SUCCESS",
        )

        return JobResult(job=job, status="SUCCESS")

    if job.job_type == "convert":
        dest_exists = job.outfile.exists()

        if not force and db.should_skip(
            str(job.infile), str(job.outfile), job_type="convert", dest_file_exists=dest_exists
        ):
            return JobResult(job=job, status="SKIPPED")

        job.outfile.parent.mkdir(parents=True, exist_ok=True)
        result = backend.run(job, stream_callback)

        if result.status == "SUCCESS":
            copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
            copy_covers(job.infile, job.outfile, job.preset.covers)

            db.log_conversion(
                source=str(job.infile),
                dest=str(job.outfile),
                job_type=job.job_type,
                command=None,
                status=result.status,
                error_msg=result.error_msg,
                stdout=result.stdout,
            )

        return result

    return JobResult(
        job=job,
        status="FAILED",
        error_msg=f"unknown job_type: {job.job_type}",
    )


def run_all(
    jobs: list[ConversionJob],
    backend: ConversionBackend,
    db: ConversionDB,
    force: bool,
    workers: int,
    worker_model: str,
    verbose: bool,
    progress: Any,
    master_task: Any,
) -> dict[str, int]:
    """
    Execute a list of ConversionJobs using a thread or process pool.

    Args:
        jobs: List of conversion jobs to execute.
        backend: The conversion backend to use.
        db: The history database for logging and resume checks.
        force: If True, skip resume checks and force re-processing.
        workers: Maximum number of parallel workers.
        worker_model: Either "thread" for ThreadPoolExecutor or "process" for ProcessPoolExecutor.
        verbose: If True, enable verbose output streaming.
        progress: Optional rich.progress.Progress instance.
        master_task: Optional rich.progress.TaskID for the master progress task.

    Returns:
        A dict with keys "success", "skipped", and "failed" counting each job outcome.
    """
    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    if not jobs:
        return summary

    stream_cb: Optional[Callable[[str], None]] = None
    if verbose:
        stream_cb = lambda line: print(line)  # noqa: E731

    ExecutorCls = ThreadPoolExecutor if worker_model == "thread" else ProcessPoolExecutor

    with ExecutorCls(max_workers=workers) as executor:
        futures = {
            executor.submit(run_job, job, backend, db, force, stream_cb, progress, master_task): job
            for job in jobs
        }

        for future in as_completed(futures):
            result = future.result()

            if result.status == "SUCCESS":
                summary["success"] += 1
            elif result.status == "SKIPPED":
                summary["skipped"] += 1
            else:
                summary["failed"] += 1

            if progress is not None and master_task is not None:
                progress.update(
                    master_task,
                    advance=1,
                    description=f"{result.job.infile.name}: {result.status}",
                )

    return summary
