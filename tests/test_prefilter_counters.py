"""tests/test_prefilter_counters.py: Tests for the preverify phase counters.

The improved prefilter advances the master bar AND calls ``sink.set_counters``
every 50 candidates (throttled) with the final cumulative values pushed by
the finally-block. Demoted file log lines are also throttled to every 50
demotes to keep the bar responsive for 25k+ file lists.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.types import ConversionJob
from src.ui.progress.rich_sink import RichProgressSink


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)


def _make_job(outfile: Path) -> ConversionJob:
    return ConversionJob(
        infile=Path("/src.flac"), outfile=outfile,
        preset=MagicMock(), job_type="convert",
    )


class TestPrefilterCallsSetCounters:
    """When --verify-skip is on, the prefilter must push counter updates to the sink."""

    def test_counters_throttled_and_final(self) -> None:
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        # 30 OK + 5 NOT_OK = 35 candidates.
        outfiles_ok = [_closed_temp_file(".flac", b"valid") for _ in range(30)]
        outfiles_bad = [_closed_temp_file(".flac", b"corrupt") for _ in range(5)]
        try:
            jobs = [_make_job(p) for p in (*outfiles_ok, *outfiles_bad)]

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            mock_args = MagicMock()
            mock_args.force = False
            mock_args.verify_skip = True

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")

            mock_sink = MagicMock()

            verify_results: list[VerifyResult] = []
            verify_results.extend(
                VerifyResult(status=VerifyStatus.OK, fmt="FLAC/PCM_16") for _ in range(30)
            )
            verify_results.extend(
                VerifyResult(status=VerifyStatus.NOT_OK, reason="truncated") for _ in range(5)
            )

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.side_effect = verify_results
                    pending, skipped = prefilter_jobs(jobs, mock_ctx, sink=mock_sink)

            # All 30 OK skipped, all 5 NOT_OK pending.
            assert len(skipped) == 30
            assert len(pending) == 5

            # Throttling at every 50 advances: with 35 candidates (less than 50)
            # the intermediate throttled call never fires — only the unconditional
            # finally-block push with the final cumulative totals (5 demote, 30 kept).
            set_calls = mock_sink.set_counters.call_args_list
            assert set_calls, "set_counters was never called"
            assert len(set_calls) == 1, f"expected 1 call, got {len(set_calls)}: {set_calls}"
            final = set_calls[0]
            assert final.kwargs == {"demoted": 5, "kept": 30}
        finally:
            for p in (*outfiles_ok, *outfiles_bad):
                p.unlink(missing_ok=True)

    def test_counters_summary_line_at_end(self) -> None:
        from src.audio.integrity import VerifyResult, VerifyStatus
        from src.app.pipeline.prefilter import prefilter_jobs

        out_ok = _closed_temp_file(".flac", b"ok")
        out_bad = _closed_temp_file(".flac", b"bad")
        try:
            jobs = [_make_job(out_ok), _make_job(out_bad)]
            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            mock_args = MagicMock()
            mock_args.force = False
            mock_args.verify_skip = True
            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_sink = MagicMock()

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                with patch("src.app.pipeline.prefilter.verify_file") as mock_vf:
                    mock_vf.side_effect = [
                        VerifyResult(status=VerifyStatus.OK, fmt="FLAC/PCM_16"),
                        VerifyResult(status=VerifyStatus.NOT_OK, reason="bad"),
                    ]
                    prefilter_jobs(jobs, mock_ctx, sink=mock_sink)

            # The final summary line must include demoted + kept counts.
            log_lines = [c.args[0] for c in mock_sink.log.call_args_list]
            assert any("1 demoted" in m for m in log_lines), log_lines
            assert any("1 kept" in m for m in log_lines), log_lines
        finally:
            out_ok.unlink(missing_ok=True)
            out_bad.unlink(missing_ok=True)


class TestRichSinkSetCounters:
    """RichProgressSink must accept set_counters without raising (no-op when
    no renderer is active)."""

    def test_set_counters_no_op_when_idle(self) -> None:
        sink = RichProgressSink()
        sink.set_counters(demoted=3, kept=10)  # no renderer: no-op, no crash

    def test_set_counters_calls_renderer(self) -> None:
        sink = RichProgressSink()
        sink.start_phase("Phase", total=10)
        sink.set_counters(demoted=2, kept=5)
        assert sink._renderer is not None
        assert sink._renderer._demoted == 2
        assert sink._renderer._kept == 5


class TestNullSinkSetCounters:
    """The null/verbose sinks must implement set_counters as a no-op."""

    def test_null_sink_set_counters(self) -> None:
        from src.ui.progress.null_sink import NullProgressSink

        NullProgressSink().set_counters(demoted=1, kept=2)  # no-op, no crash

    def test_verbose_sink_set_counters(self) -> None:
        from src.ui.progress.verbose_sink import VerboseProgressSink

        VerboseProgressSink().set_counters(demoted=1, kept=2)  # no-op, no crash
