"""execution/run_job.py: Single-job execution — copy / convert / skip branches."""

from __future__ import annotations

import shutil
from pathlib import Path
from queue import Queue
from typing import Callable, Optional

from src.backends.base import ConversionBackend
from src.history.db import ConversionDB, DBWriteQueue
from src.models.types import ConversionJob, JobStatus
from src.sidecars.manager import copy_covers, copy_lyrics

from src.execution.events import JobEventKind


def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    """
    Verify the output file exists and has a reasonable size.

    Returns:
        (is_valid, error_message) - is_valid is True if file exists and has content.
    """
    if not job.outfile.exists():
        return False, f"Output file not found: {job.outfile}"

    size = job.outfile.stat().st_size
    if size == 0:
        return False, f"Output file is empty: {job.outfile}"

    return True, None


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """
    Execute a single ConversionJob.

    Args:
        job: The conversion job to execute.
        backend: The conversion backend to use.
        db_path: Path to the history SQLite database (for resume checks and logging).
        force: If True, skip resume checks and force re-processing.
        stream_callback: Optional callback for streaming output line-by-line.
        events: Optional cross-process/thread queue for UI events. Workers push
            (JobEventKind.STARTED, infile_name) when they begin and
            (JobEventKind.FINISHED, infile_name) when they finish. The main
            thread drains the queue and updates the UI.

    Returns:
        A tuple of (status, infile_name, error_msg).
    """
    infile_name = str(job.infile)

    db = ConversionDB(Path(db_path))

    # Send activity event to update UI
    if events is not None:
        events.put((JobEventKind.ACTIVITY, job.job_type))
        events.put((JobEventKind.STARTED, infile_name))

    try:
        if job.job_type == "skip":
            status: JobStatus = "SKIPPED"
            error_msg: str | None = "lossy, leave"

        elif job.job_type == "copy":
            try:
                job.outfile.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(job.infile, job.outfile)
            except (shutil.Error, OSError) as e:
                print(f"[runner] copy failed for {job.infile} -> {job.outfile}: {e}")
                status = "FAILED"
                error_msg = str(e)
            else:
                # Verify output file before marking as success
                is_valid, verify_error = _verify_output_file(job)
                if not is_valid:
                    status = "FAILED"
                    error_msg = verify_error
                else:
                    copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                    copy_covers(job.infile, job.outfile, job.preset.covers)
                    file_size = job.outfile.stat().st_size
                    db.log_conversion(
                        source=str(job.infile),
                        dest=str(job.outfile),
                        job_type=job.job_type,
                        command=None,
                        status="SUCCESS",
                        file_size=file_size,
                    )
                    status = "SUCCESS"
                    error_msg = None

        elif job.job_type == "convert":
            dest_exists = job.outfile.exists()
            dest_size = job.outfile.stat().st_size if dest_exists else None

            if not force and db.should_skip(
                str(job.infile), str(job.outfile), job_type="convert",
                dest_file_exists=dest_exists, dest_file_size=dest_size,
            ):
                status = "SKIPPED"
                error_msg = None
                return status, infile_name, error_msg

            job.outfile.parent.mkdir(parents=True, exist_ok=True)
            result = backend.run(job, stream_callback)

            if result.status == "SUCCESS":
                # Verify output file before marking as success
                is_valid, verify_error = _verify_output_file(job)
                if not is_valid:
                    result.status = "FAILED"
                    result.error_msg = verify_error
                else:
                    copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                    copy_covers(job.infile, job.outfile, job.preset.covers)
                    output_size = job.outfile.stat().st_size
                    db.log_conversion(
                        source=str(job.infile),
                        dest=str(job.outfile),
                        job_type=job.job_type,
                        command=None,
                        status=result.status,
                        error_msg=result.error_msg,
                        stdout=result.stdout,
                        file_size=output_size,
                    )

            status = result.status
            error_msg = result.error_msg

        else:
            status = "FAILED"
            error_msg = f"unknown job_type: {job.job_type}"

    finally:
        db.close()
        if events is not None:
            events.put((JobEventKind.FINISHED, infile_name))

    return status, infile_name, error_msg
