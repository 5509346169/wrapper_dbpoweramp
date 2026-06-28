"""tests/test_pre_verify_demotion.py: Tests for the pre-verify demotion gate."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.types import ConversionJob


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    """Create a temp file, close its handle, return the Path."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)


class TestPreVerifyDemotion:
    """Tests for the --verify-skip pre-verify demotion gate in prefilter.py."""

    def test_skip_candidate_ok_is_still_skipped(self):
        """A skip candidate with OK output stays skipped."""
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        outfile = _closed_temp_file(".flac", b"valid flac content")
        try:
            job = ConversionJob(
                infile=Path("/src.flac"),
                outfile=outfile,
                preset=MagicMock(),
                job_type="convert",
            )

            mock_db = MagicMock()
            # should_skip returns True (skip candidate)
            mock_db.should_skip.return_value = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.return_value = VerifyResult(
                        status=VerifyStatus.OK,
                        fmt="FLAC/PCM_16",
                        duration_s=10.0,
                    )

                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    pending, skipped = prefilter_jobs([job], mock_ctx)

                    mock_vf.assert_called_once_with(outfile)
                    assert job in skipped
                    assert job not in pending
        finally:
            outfile.unlink(missing_ok=True)

    def test_skip_candidate_not_ok_is_demoted_to_pending(self):
        """A skip candidate with NOT_OK output is demoted to pending (forced reconvert)."""
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        outfile = _closed_temp_file(".flac", b"truncated or corrupt content")
        try:
            job = ConversionJob(
                infile=Path("/src.flac"),
                outfile=outfile,
                preset=MagicMock(),
                job_type="convert",
            )

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.return_value = VerifyResult(
                        status=VerifyStatus.NOT_OK,
                        reason="Truncated – header says 44100 frames, decoded 1234",
                    )

                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    pending, skipped = prefilter_jobs([job], mock_ctx)

                    mock_vf.assert_called_once_with(outfile)
                    assert job in pending
                    assert job not in skipped
        finally:
            outfile.unlink(missing_ok=True)

    def test_skip_candidate_unsupported_still_skipped(self):
        """A skip candidate with UNSUPPORTED output is trusted (we can't decode it)."""
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        outfile = _closed_temp_file(".tak", b"some content")
        try:
            job = ConversionJob(
                infile=Path("/src.flac"),
                outfile=outfile,
                preset=MagicMock(),
                job_type="convert",
            )

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.return_value = VerifyResult(
                        status=VerifyStatus.UNSUPPORTED,
                        reason="no decoder for .tak",
                    )

                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    pending, skipped = prefilter_jobs([job], mock_ctx)

                    assert job in skipped
                    assert job not in pending
        finally:
            outfile.unlink(missing_ok=True)

    def test_non_skip_candidate_not_touched_by_preverify(self):
        """A job with no matching history row is not affected by pre-verify."""
        from src.app.pipeline.prefilter import prefilter_jobs

        outfile = _closed_temp_file(".flac", b"content")
        try:
            job = ConversionJob(
                infile=Path("/src.flac"),
                outfile=outfile,
                preset=MagicMock(),
                job_type="convert",
            )

            mock_db = MagicMock()
            # should_skip returns False (not a skip candidate because dest doesn't exist)
            mock_db.should_skip.return_value = False

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    pending, skipped = prefilter_jobs([job], mock_ctx)

                    # verify_file should NOT be called since this isn't a skip candidate
                    mock_vf.assert_not_called()
                    assert job in pending
        finally:
            outfile.unlink(missing_ok=True)

    def test_verify_skip_false_skips_preverify(self):
        """When --verify-skip is False, verify_file is never called."""
        from src.app.pipeline.prefilter import prefilter_jobs

        job = ConversionJob(
            infile=Path("/src.flac"),
            outfile=Path("/dst.flac"),
            preset=MagicMock(),
            job_type="convert",
        )

        mock_db = MagicMock()
        mock_db.should_skip.return_value = True

        with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
            with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                mock_args = MagicMock()
                mock_args.force = False
                mock_args.verify_skip = False

                mock_ctx = MagicMock()
                mock_ctx.args = mock_args
                mock_ctx.db_path = Path("/tmp/history.db")

                pending, skipped = prefilter_jobs([job], mock_ctx)

                mock_vf.assert_not_called()
                assert job in skipped

    def test_preverify_emits_sink_progress(self):
        """When --verify-skip is set, prefilter emits start_phase + advance per candidate."""
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        out_a = _closed_temp_file(".flac", b"valid")
        out_b = _closed_temp_file(".flac", b"corrupt")
        try:
            jobs = [
                ConversionJob(
                    infile=Path("/a.flac"), outfile=out_a,
                    preset=MagicMock(), job_type="convert",
                ),
                ConversionJob(
                    infile=Path("/b.flac"), outfile=out_b,
                    preset=MagicMock(), job_type="convert",
                ),
            ]

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.side_effect = [
                        VerifyResult(status=VerifyStatus.OK, fmt="FLAC/PCM_16"),
                        VerifyResult(
                            status=VerifyStatus.NOT_OK,
                            reason="truncated",
                        ),
                    ]

                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    mock_sink = MagicMock()

                    pending, skipped = prefilter_jobs(jobs, mock_ctx, sink=mock_sink)

                    # Bar opened once with the candidate count, advanced per call,
                    # and closed exactly once at the end.
                    mock_sink.start_phase.assert_called_once()
                    phase_name = mock_sink.start_phase.call_args.args[0]
                    phase_total = mock_sink.start_phase.call_args.kwargs["total"]
                    assert "reverify" in phase_name.lower() or "pre-verif" in phase_name.lower()
                    assert phase_total == 2
                    assert mock_sink.advance.call_count == 2
                    mock_sink.stop_phase.assert_called_once()

                    # Demoted file ended up pending, OK file ended up skipped.
                    assert jobs[0] in skipped and jobs[0] not in pending
                    assert jobs[1] in pending and jobs[1] not in skipped

                    # Demotion was reported via the log sink.
                    log_calls = [c.args[0] for c in mock_sink.log.call_args_list]
                    assert any("demoted" in m for m in log_calls)
        finally:
            out_a.unlink(missing_ok=True)
            out_b.unlink(missing_ok=True)

    def test_preverify_sink_none_uses_null_sink(self):
        """Passing sink=None must not raise and must still produce correct split."""
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        outfile = _closed_temp_file(".flac", b"corrupt")
        try:
            job = ConversionJob(
                infile=Path("/a.flac"), outfile=outfile,
                preset=MagicMock(), job_type="convert",
            )

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.return_value = VerifyResult(
                        status=VerifyStatus.NOT_OK, reason="bad",
                    )

                    mock_args = MagicMock()
                    mock_args.force = False
                    mock_args.verify_skip = True

                    mock_ctx = MagicMock()
                    mock_ctx.args = mock_args
                    mock_ctx.db_path = Path("/tmp/history.db")

                    pending, skipped = prefilter_jobs([job], mock_ctx, sink=None)

                    assert job in pending
                    assert job not in skipped
        finally:
            outfile.unlink(missing_ok=True)
