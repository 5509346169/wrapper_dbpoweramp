"""tests/test_run_job_failure_logging.py: Tests for FAILED-row logging in run_job.

Before the fix, when CoreConverter returned exit-0 but the post-write verifier
caught an empty/corrupt output, run_job flipped ``result.status`` to FAILED but
never wrote that FAILED row to history. This caused a re-process loop on every
subsequent run. The fix:

  1. Writes a FAILED row (with verify_status/reason) so the next run sees it.
  2. Adds ``ConversionDB.last_failure()`` so the runner can short-circuit
     repeated failures without paying for another doomed CoreConverter call.

These tests cover both behaviours.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.types import ConversionJob, JobResult


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)


@pytest.fixture
def history_db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


def _job_with_outfile(outfile: Path) -> ConversionJob:
    """Build a minimal ConversionJob shape used by run_job."""
    return MagicMock(
        spec_set=[
            "infile",
            "outfile",
            "preset",
            "job_type",
            "is_lossy_source",
            "reason",
        ],
        infile=Path("C:/src.m4a"),
        outfile=outfile,
        job_type="convert",
        is_lossy_source=False,
        reason=None,
        preset=MagicMock(lyrics=None, covers=None),
    )


class TestPostVerifyFailureLogsRow:
    """When CoreConverter returns 0 but the verifier catches an empty output,
    run_job must write a FAILED row (with verify_status='NOT_OK') so the next
    pipeline run can short-circuit."""

    def test_post_verify_empty_output_logs_failed(self, history_db_path: Path) -> None:
        from src.execution import run_job

        outfile = _closed_temp_file(".m4a", b"")  # empty!
        try:
            job = _job_with_outfile(outfile)
            backend = MagicMock()
            backend.run.return_value = JobResult(
                job=job, status="SUCCESS", stdout="CoreConverter exit 0",
            )

            mock_db = MagicMock()
            # Pre-existing SUCCESS row is missing — should_skip returns False.
            mock_db.should_skip.return_value = False
            mock_db.last_failure.return_value = None

            with patch("src.execution.run_job.ConversionDB", return_value=mock_db):
                status, _, _ = run_job.run_job(
                    job=job, backend=backend, db_path=str(history_db_path),
                    force=False, stream_callback=None, events=None,
                )

            assert status == "FAILED"
            # The fix: a FAILED row must be logged with NOT_OK verify metadata.
            logged = mock_db.log_conversion.call_args_list[0]
            assert logged.kwargs["status"] == "FAILED"
            assert logged.kwargs["verify_status"] == "NOT_OK"
            assert "empty" in (logged.kwargs["verify_reason"] or "").lower()

        finally:
            outfile.unlink(missing_ok=True)

    def test_prior_failure_skips_subprocess(self, history_db_path: Path) -> None:
        """When last_failure() returns a row, run_job must NOT call the backend."""
        from src.execution import run_job

        outfile = _closed_temp_file(".m4a", b"")
        try:
            job = _job_with_outfile(outfile)
            backend = MagicMock()

            mock_db = MagicMock()
            mock_db.should_skip.return_value = False
            mock_db.last_failure.return_value = {
                "error_msg": "previously failed: empty output",
                "stdout": "CoreConverter exit 0\n",
                "verify_status": "NOT_OK",
                "verify_reason": "file is empty",
            }

            with patch("src.execution.run_job.ConversionDB", return_value=mock_db):
                status, _, err = run_job.run_job(
                    job=job, backend=backend, db_path=str(history_db_path),
                    force=False, stream_callback=None, events=None,
                )

            # The backend must NOT have been invoked.
            backend.run.assert_not_called()
            assert status == "FAILED"
            assert "previously failed" in err

            # And the FAILED row must be re-logged so the timestamp stays fresh.
            assert mock_db.log_conversion.called
            logged = mock_db.log_conversion.call_args_list[0]
            assert logged.kwargs["status"] == "FAILED"
            assert "previously failed" in (logged.kwargs["error_msg"] or "")

        finally:
            outfile.unlink(missing_ok=True)

    def test_backend_returns_failed_logs_row(self, history_db_path: Path) -> None:
        """When the backend returns FAILED directly, a FAILED row must be logged."""
        from src.execution import run_job

        outfile = _closed_temp_file(".m4a", b"")
        try:
            job = _job_with_outfile(outfile)
            backend = MagicMock()
            backend.run.return_value = JobResult(
                job=job, status="FAILED",
                error_msg="CoreConverter exited with code 2",
                stdout="parse error",
            )

            mock_db = MagicMock()
            mock_db.should_skip.return_value = False
            mock_db.last_failure.return_value = None

            with patch("src.execution.run_job.ConversionDB", return_value=mock_db):
                status, _, err = run_job.run_job(
                    job=job, backend=backend, db_path=str(history_db_path),
                    force=False, stream_callback=None, events=None,
                )

            assert status == "FAILED"
            assert "exit" in err.lower() or "CoreConverter" in err

            logged = mock_db.log_conversion.call_args_list[0]
            assert logged.kwargs["status"] == "FAILED"
            assert logged.kwargs["error_msg"] == "CoreConverter exited with code 2"

        finally:
            outfile.unlink(missing_ok=True)


class TestConversionDBLastFailure:
    """ConversionDB.last_failure() must distinguish FAILED vs missing-vs-SUCCESS."""

    def test_last_failure_returns_row_for_failed(self, tmp_path: Path) -> None:
        from src.history.db import ConversionDB

        db = ConversionDB(tmp_path / "history.db")
        try:
            db.log_conversion(
                source="A:/src.m4a", dest="B:/dst.m4a",
                job_type="convert", command=None, status="FAILED",
                error_msg="empty output", stdout="",
            )

            row = db.last_failure("A:/src.m4a", "B:/dst.m4a", "convert")
            assert row is not None
            assert row["error_msg"] == "empty output"

        finally:
            db.close()

    def test_last_failure_none_for_missing(self, tmp_path: Path) -> None:
        from src.history.db import ConversionDB

        db = ConversionDB(tmp_path / "history.db")
        try:
            assert db.last_failure("X:/nope.m4a", "Y:/nope.m4a", "convert") is None
        finally:
            db.close()

    def test_last_failure_none_for_success(self, tmp_path: Path) -> None:
        from src.history.db import ConversionDB

        db = ConversionDB(tmp_path / "history.db")
        try:
            db.log_conversion(
                source="A:/src.m4a", dest="B:/dst.m4a",
                job_type="convert", command=None, status="SUCCESS",
            )
            # A SUCCESS row exists; last_failure() should NOT report it.
            assert db.last_failure("A:/src.m4a", "B:/dst.m4a", "convert") is None
        finally:
            db.close()
