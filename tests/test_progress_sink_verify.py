"""tests/test_progress_sink_verify.py: Tests for VERIFY_RESULT event rendering in both sinks."""

from __future__ import annotations

import io
import sys

import pytest

from src.ui.progress.protocol import SubtaskID


class TestRichSinkVerifyResult:
    """Tests for RichProgressSink.log_verify_result()."""

    def test_log_verify_ok(self):
        from src.ui.progress.rich_sink import RichProgressSink

        sink = RichProgressSink()
        # log_verify_result should not raise
        sink.log_verify_result("test.flac", "OK", None, "FLAC/PCM_16", 10.5)
        assert len(sink._log_lines) == 1
        assert "[verify] Okay" in sink._log_lines[0]

    def test_log_verify_not_ok(self):
        from src.ui.progress.rich_sink import RichProgressSink

        sink = RichProgressSink()
        sink.log_verify_result("test.flac", "NOT_OK", "Truncated – header says 44100 frames, decoded 1234", "FLAC/PCM_16", 1.5)
        assert len(sink._log_lines) == 1
        assert "[verify] Not -" in sink._log_lines[0]
        assert "Truncated" in sink._log_lines[0]

    def test_log_verify_unsupported(self):
        from src.ui.progress.rich_sink import RichProgressSink

        sink = RichProgressSink()
        sink.log_verify_result("test.tak", "UNSUPPORTED", "no decoder for .tak", None, None)
        assert len(sink._log_lines) == 1
        assert "[verify] Skipped -" in sink._log_lines[0]
        assert "no decoder" in sink._log_lines[0]


class TestVerboseSinkVerifyResult:
    """Tests for VerboseProgressSink.log_verify_result()."""

    def test_log_verify_ok(self, capsys):
        from src.ui.progress.verbose_sink import VerboseProgressSink

        sink = VerboseProgressSink()
        sink.log_verify_result("/path/to/test.flac", "OK", None, "FLAC/PCM_16", 3.42)
        captured = capsys.readouterr()
        assert "verify" in captured.out
        assert "Okay" in captured.out
        assert "3.42s" in captured.out
        assert "FLAC/PCM_16" in captured.out

    def test_log_verify_not_ok(self, capsys):
        from src.ui.progress.verbose_sink import VerboseProgressSink

        sink = VerboseProgressSink()
        sink.log_verify_result("/path/to/test.flac", "NOT_OK", "Truncated", None, 1.5)
        captured = capsys.readouterr()
        assert "verify" in captured.out
        assert "Not - Truncated" in captured.out

    def test_log_verify_unsupported(self, capsys):
        from src.ui.progress.verbose_sink import VerboseProgressSink

        sink = VerboseProgressSink()
        sink.log_verify_result("/path/to/test.tak", "UNSUPPORTED", "no decoder for .tak", None, None)
        captured = capsys.readouterr()
        assert "Skipped -" in captured.out


class TestNullSinkVerifyResult:
    """Tests for NullProgressSink.log_verify_result() (no-op)."""

    def test_noop(self):
        from src.ui.progress.null_sink import NullProgressSink

        sink = NullProgressSink()
        # Should not raise
        sink.log_verify_result("test.flac", "OK", None, "FLAC/PCM_16", 10.5)


class TestEventDrainVerifyResult:
    """Tests for VERIFY_RESULT in the event drain."""

    def test_drain_verifiesult(self):
        from queue import Queue

        from src.execution.event_drain import _drain_events_into_ui
        from src.execution.events import JobEventKind
        from src.ui.progress.null_sink import NullProgressSink

        events: Queue = Queue()
        events.put((
            JobEventKind.VERIFY_RESULT,
            ("test.flac", "OK", None, "FLAC/PCM_16", 10.5),
        ))

        sink = NullProgressSink()
        job_tasks: dict = {}
        _drain_events_into_ui(events, sink, job_tasks)
        # No exception means success
