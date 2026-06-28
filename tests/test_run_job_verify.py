"""tests/test_run_job_verify.py: Integration tests for post-write verification in run_job."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.types import ConversionJob, JobStatus, PresetConfig


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    """Create a temp file, close its handle, return the Path."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)


class TestRunJobVerify:
    """Tests for _verify_output_file integration in run_job."""

    def test_verify_file_not_found(self):
        """Output file not found → NOT_OK."""
        from src.execution.run_job import _verify_output_file

        job = MagicMock(spec=ConversionJob)
        job.outfile = Path("/nonexistent/file.flac")
        job.job_type = "convert"

        is_valid, error_msg, verify_status, verify_reason, verify_duration_s = _verify_output_file(job)

        assert is_valid is False
        assert verify_status == "NOT_OK"
        assert "not found" in verify_reason

    def test_verify_empty_file(self):
        """Empty output file → NOT_OK."""
        from src.execution.run_job import _verify_output_file

        path = _closed_temp_file(".flac", b"")
        try:
            job = MagicMock(spec=ConversionJob)
            job.outfile = path
            job.job_type = "convert"

            is_valid, error_msg, verify_status, verify_reason, verify_duration_s = _verify_output_file(job)

            assert is_valid is False
            assert verify_status == "NOT_OK"
            assert "empty" in verify_reason
        finally:
            path.unlink(missing_ok=True)

    def test_verify_copy_job_uses_size_check_only(self):
        """For copy jobs, only existence + size is checked (no decode)."""
        from src.execution.run_job import _verify_output_file

        path = _closed_temp_file(".flac", b"file content here")
        try:
            job = MagicMock(spec=ConversionJob)
            job.outfile = path
            job.job_type = "copy"

            with patch("src.execution.run_job.verify_file") as mock_vf:
                is_valid, error_msg, verify_status, verify_reason, verify_duration_s = _verify_output_file(job)
                mock_vf.assert_not_called()

            assert is_valid is True
            assert verify_status == "OK"
        finally:
            path.unlink(missing_ok=True)


class TestVerifyResultShort:
    """Tests for VerifyResult.short property."""

    def test_ok_short(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.OK)
        assert r.short == "Okay"

    def test_not_ok_short(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.NOT_OK, reason="Truncated – header says 1234 frames")
        assert r.short == "Not - Truncated – header says 1234 frames"

    def test_unsupported_short(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.UNSUPPORTED, reason="no decoder for .tak")
        assert r.short == "Skipped - no decoder for .tak"
