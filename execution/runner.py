"""execution/runner.py: Execute ConversionJob lists using the configured backend."""

from __future__ import annotations

import shutil
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

from backends.base import ConversionBackend
from history.db import ConversionDB
from models.types import ConversionJob, JobResult, JobStatus
from sidecars.manager import copy_covers, copy_lyrics


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    progress_view: Any | None = None,
) -> tuple[JobStatus, str, str | None]:
    """
    Execute a single ConversionJob.

    Args:
        job: The conversion job to execute.
        backend: The conversion backend to use.
        db_path: Path to the history SQLite database.
        force: If True, skip resume checks and force re-processing.
        stream_callback: Optional callback for streaming output line-by-line.
        progress_view: Optional ProgressView for per-job progress bars in parallel mode.

    Returns:
        A tuple of (status, infile_name, error_msg).
    """
    infile_name = job.infile.name

    db = ConversionDB(Path(db_path))

    job_task: Any | None = None
    if progress_view is not None:
        job_task = progress_view.add_job_task(infile_name)

    try:
        if job.job_type == "skip":
            status: JobStatus = "SKIPPED"
            error_msg: str | None = "lossy, leave"

        elif job.job_type == "copy":
            try:
                job.outfile.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(job.infile, job.outfile)
            except Exception as e:
                status = "FAILED"
                error_msg = str(e)
            else:
                copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                copy_covers(job.infile, job.outfile, job.preset.covers)
                db.log_conversion(
                    source=str(job.infile),
                    dest=str(job.outfile),
                    job_type=job.job_type,
                    command=None,
                    status="SUCCESS",
                )
                status = "SUCCESS"
                error_msg = None

        elif job.job_type == "convert":
            dest_exists = job.outfile.exists()

            if not force and db.should_skip(
                str(job.infile), str(job.outfile), job_type="convert", dest_file_exists=dest_exists
            ):
                status = "SKIPPED"
                error_msg = None
                if job_task is not None and progress_view is not None:
                    progress_view.remove_job_task(job_task)
                return status, infile_name, error_msg

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

            status = result.status
            error_msg = result.error_msg

        else:
            status = "FAILED"
            error_msg = f"unknown job_type: {job.job_type}"

    finally:
        if job_task is not None and progress_view is not None:
            progress_view.remove_job_task(job_task)

    return status, infile_name, error_msg


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
    progress_view: Any | None = None,
) -> tuple[dict[str, int], list[Future]]:
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
        progress_view: Optional ProgressView instance for per-job bars in parallel mode.

    Returns:
        A tuple of (summary dict with success/skipped/failed counts, list of futures).
        Callers in parallel mode iterate the futures externally while a polling loop
        drives the Live display.
    """
    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    if not jobs:
        return summary, []

    stream_cb: Optional[Callable[[str], None]] = None
    if verbose:
        stream_cb = lambda line: print(line)  # noqa: E731

    ExecutorCls = ThreadPoolExecutor if worker_model == "thread" else ProcessPoolExecutor

    futures: list[Future] = []

    with ExecutorCls(max_workers=workers) as executor:
        futures = [
            executor.submit(
                run_job,
                job,
                backend,
                str(db.db_path),
                force,
                stream_cb,
                progress_view,
            )
            for job in jobs
        ]

        if workers > 1:
            return summary, futures

        for future in as_completed(futures):
            status, infile_name, error_msg = future.result()

            if status == "SUCCESS":
                summary["success"] += 1
            elif status == "SKIPPED":
                summary["skipped"] += 1
            else:
                summary["failed"] += 1

            if progress is not None and master_task is not None:
                progress.update(master_task, advance=1)

    return summary, futures
