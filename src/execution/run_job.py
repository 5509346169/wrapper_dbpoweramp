"""execution/run_job.py: Single-job execution — copy / convert / skip branches."""

from __future__ import annotations

import shutil
import time as _time
from pathlib import Path
from queue import Queue
from typing import Callable, Optional

from src.audio.integrity import VerifyStatus, verify_file
from src.backends.base import Backend, ConversionBackend
from src.history.db import ConversionDB, DBWriteQueue
from src.models.types import ConversionJob, JobResult, JobStatus
from src.sidecars.manager import copy_covers, copy_lyrics

from src.execution.events import JobEventKind


def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None, str | None, str | None, float | None]:
    """
    Post-write integrity check — runs on-the-fly inside run_job, before
    the FINISHED event is enqueued and before history is logged.

    For job_type == "convert": full-frame decode via src.audio.integrity.verify_file.
    For job_type == "copy":    existence + non-empty size only (a copy of an
                               already-trusted file is assumed good — re-running
                               the source verifier on it is wasted work).
    For job_type == "skip":    not called (no output file).

    Returns:
        (is_valid, error_msg, verify_status, verify_reason, verify_duration_s)
        On OK: (True, None, "OK", None, duration_s)
        On UNSUPPORTED: (True, f"verify skipped: {reason}", "UNSUPPORTED", reason, duration_s)
        On NOT_OK: (False, "Not - <reason>", "NOT_OK", reason, duration_s)
        On NOT_FOUND/EMPTY: (False, error_msg, "NOT_OK", error_msg, None)
    """
    if not job.outfile.exists():
        return False, f"Output file not found: {job.outfile}", "NOT_OK", f"Output file not found: {job.outfile}", None

    size = job.outfile.stat().st_size
    if size == 0:
        return False, f"Output file is empty: {job.outfile}", "NOT_OK", f"Output file is empty: {job.outfile}", None

    if job.job_type != "convert":
        return True, None, "OK", None, None

    result = verify_file(job.outfile)
    if result.status is VerifyStatus.OK:
        return True, None, "OK", None, result.duration_s
    if result.status is VerifyStatus.UNSUPPORTED:
        return True, f"verify skipped: {result.reason}", "UNSUPPORTED", result.reason, result.duration_s
    return False, result.short, "NOT_OK", result.reason, result.duration_s


def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
    retry_failed: bool = False,
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
        retry_failed: If True, bypass the ``last_failure`` short-circuit for
            convert jobs. The prefilter only routes previously-failed jobs
            into the pending list when ``--failed-only`` is set, so we must
            actually invoke the backend to give them a fresh attempt instead
            of replaying the recorded error_msg/stdout. ``--force`` already
            implies this behaviour, but ``retry_failed`` lets ``--failed-only``
            get the same retry semantics without taking the broader
            ``--force`` cost of ignoring the SUCCESS cache.

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
                copy_start = _time.monotonic()
                job.outfile.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(job.infile, job.outfile)
                copy_elapsed = _time.monotonic() - copy_start
            except (shutil.Error, OSError) as e:
                print(f"[runner] copy failed for {job.infile} -> {job.outfile}: {e}")
                status = "FAILED"
                error_msg = str(e)
                copy_size: int | None = job.outfile.stat().st_size if job.outfile.exists() else None
                db.log_conversion(
                    source=str(job.infile),
                    dest=str(job.outfile),
                    job_type=job.job_type,
                    command=None,
                    status="FAILED",
                    error_msg=error_msg,
                    stdout=None,
                    file_size=copy_size,
                    verify_status=None,
                    verify_reason=None,
                    verify_format=None,
                    verify_duration_s=None,
                )
                if events is not None:
                    events.put((JobEventKind.VERIFY_RESULT, (infile_name, "UNSUPPORTED", None, None, None)))
                    events.put((JobEventKind.CONVERT_RESULT,
                                (str(job.infile), str(job.outfile), "copy",
                                 copy_size, 0.0, "FAILED", error_msg)))
            else:
                # Verify output file before marking as success
                is_valid, verify_error, verify_status, verify_reason, verify_duration_s = _verify_output_file(job)
                copy_size = job.outfile.stat().st_size
                if events is not None:
                    events.put((JobEventKind.VERIFY_RESULT,
                                (infile_name, verify_status, verify_reason, None, verify_duration_s)))
                    events.put((JobEventKind.CONVERT_RESULT,
                                (str(job.infile), str(job.outfile), "copy",
                                 copy_size, copy_elapsed, "SUCCESS", None)))
                if not is_valid:
                    status = "FAILED"
                    error_msg = verify_error
                    db.log_conversion(
                        source=str(job.infile),
                        dest=str(job.outfile),
                        job_type=job.job_type,
                        command=None,
                        status="FAILED",
                        error_msg=verify_error,
                        stdout=None,
                        file_size=copy_size,
                        verify_status=verify_status,
                        verify_reason=verify_reason,
                        verify_format=None,
                        verify_duration_s=verify_duration_s,
                    )
                else:
                    copy_lyrics(job.infile, job.outfile, job.preset.lyrics)
                    copy_covers(job.infile, job.outfile, job.preset.covers)
                    db.log_conversion(
                        source=str(job.infile),
                        dest=str(job.outfile),
                        job_type=job.job_type,
                        command=None,
                        status="SUCCESS",
                        file_size=copy_size,
                        verify_status=verify_status,
                        verify_reason=verify_reason,
                        verify_format=None,
                        verify_duration_s=verify_duration_s,
                    )
                    status = "SUCCESS"
                    error_msg = verify_error

        elif job.job_type == "convert":
            dest_exists = job.outfile.exists()
            dest_size = job.outfile.stat().st_size if dest_exists else None

            # Check whether this source already failed for the same preset.
            # The default behaviour is to short-circuit: a prior FAILED row
            # tells us the subprocess call is known to fail in this
            # environment, so we just replay the recorded error and avoid
            # paying for a guaranteed-failing CoreConverter invocation. The
            # user can retry via --force, by deleting the FAILED row, or
            # -- via --retry_failed (driven by --failed-only) -- by asking
            # for a fresh attempt despite the known-bad history.
            prior_failure = (
                None if retry_failed
                else db.last_failure(str(job.infile), str(job.outfile), "convert")
            )

            if not force and not prior_failure and not retry_failed and db.should_skip(
                str(job.infile), str(job.outfile), job_type="convert",
                dest_file_exists=dest_exists, dest_file_size=dest_size,
            ):
                status = "SKIPPED"
                error_msg = None
                return status, infile_name, error_msg

            job.outfile.parent.mkdir(parents=True, exist_ok=True)

            convert_start = _time.monotonic()
            if prior_failure:
                # Skip the subprocess call; reuse the prior failure metadata so
                # the user can see *why* the previous run failed without paying
                # for another CoreConverter invocation that's already known to
                # produce the same broken output.
                result = JobResult(
                    job=job,
                    status="FAILED",
                    error_msg=prior_failure.get("error_msg") or "previously failed",
                    stdout=prior_failure.get("stdout") or "",
                )
            else:
                result = backend.run(job, stream_callback)
            convert_elapsed = _time.monotonic() - convert_start

            # Emit CONVERT_RESULT immediately so the user sees conversion time
            # before the (longer) post-write verification finishes.
            output_size = job.outfile.stat().st_size if job.outfile.exists() else None
            encoder_name = _get_encoder_name(job)
            if events is not None:
                events.put((
                    JobEventKind.CONVERT_RESULT,
                    (str(job.infile), str(job.outfile), encoder_name,
                     output_size, convert_elapsed, result.status, result.error_msg),
                ))

            if result.status == "SUCCESS":
                # Verify output file before marking as success
                is_valid, verify_error, verify_status, verify_reason, verify_duration_s = _verify_output_file(job)

                # Enqueue VERIFY_RESULT event immediately (before FINISHED event)
                if events is not None:
                    events.put((
                        JobEventKind.VERIFY_RESULT,
                        (infile_name, verify_status, verify_reason, None, verify_duration_s),
                    ))

                if not is_valid:
                    result.status = "FAILED"
                    result.error_msg = verify_error
                    output_size = job.outfile.stat().st_size if job.outfile.exists() else 0
                    db.log_conversion(
                        source=str(job.infile),
                        dest=str(job.outfile),
                        job_type=job.job_type,
                        command=None,
                        status="FAILED",
                        error_msg=verify_error,
                        stdout=result.stdout,
                        file_size=output_size,
                        verify_status=verify_status,
                        verify_reason=verify_reason,
                        verify_format=None,
                        verify_duration_s=verify_duration_s,
                    )
                    status = "FAILED"
                    error_msg = verify_error
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
                        verify_status=verify_status,
                        verify_reason=verify_reason,
                        verify_format=None,
                        verify_duration_s=verify_duration_s,
                    )
                    status = result.status
                    error_msg = result.error_msg
            else:
                # Non-success status (e.g. backend returned FAILED before verification)
                if events is not None:
                    events.put((
                        JobEventKind.VERIFY_RESULT,
                        (infile_name, "UNSUPPORTED", None, None, None),
                    ))
                # Record the failure so subsequent runs (without --force) short-circuit
                # via last_failure() and so the user can audit failed jobs with
                # purge_failed_audio.py or the GUI.
                output_size = job.outfile.stat().st_size if job.outfile.exists() else 0
                db.log_conversion(
                    source=str(job.infile),
                    dest=str(job.outfile),
                    job_type=job.job_type,
                    command=None,
                    status="FAILED",
                    error_msg=result.error_msg,
                    stdout=result.stdout,
                    file_size=output_size,
                    verify_status=None,
                    verify_reason=None,
                    verify_format=None,
                    verify_duration_s=None,
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


def _get_encoder_name(job: ConversionJob) -> str:
    """Derive a short encoder label from the job's preset and backend args.

    For dBpoweramp this is the ``-convert_to`` encoder string (e.g. ``ALAC``,
    ``qaac CVBR 256kbps``). For other backends it falls back to the preset
    extension (e.g. ``flac``). Used only for verbose/log output.
    """
    # Prefer the encoder from the active backend; fall back to the output ext.
    for be_key, be_args in job.preset.backends.items():
        if be_args.encoder:
            return be_args.encoder
    return job.preset.ext
