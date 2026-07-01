"""tests/test_run_from_index_sink.py: Tests for --index sink wiring.

Regression coverage for the bug where ``python main.py --index …`` ran the
prefilter and execute phases against a ``NullProgressSink`` so the rich
progress bar never appeared. The fix threads a single ``RichProgressSink``
from ``run_from_index.run`` through ``prefilter_jobs`` and ``execute_phases``
so one Live instance stays alive across preverify → Skipping → Copying/
Converting.

Two things are verified:

1. ``execute_phases`` accepts an externally-built sink and does NOT call
   ``sink.stop()`` on it (the caller owns its lifecycle).
2. ``run_from_index.run`` passes the same sink instance into both
   ``prefilter_jobs`` and ``execute_phases``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.app.context import MutablePhaseState


# ---------------------------------------------------------------------------
# execute_phases accepts an externally-built sink
# ---------------------------------------------------------------------------


class TestExecutePhasesAcceptsExternalSink:
    """``execute_phases(..., sink=...)`` must reuse the caller-provided sink
    and must NOT call ``.stop()`` on it (the caller owns its lifecycle)."""

    def _ctx(self, lossy_action: str | None = None) -> MagicMock:
        """Build a minimal MagicMock ctx that satisfies the execute_phases path."""
        args = MagicMock()
        args.force = False
        args.lossy_action = lossy_action
        args.no_lossy_check = True
        ctx = MagicMock()
        ctx.args = args
        ctx.db_path = Path("/tmp/history.db")
        ctx.backend = MagicMock()
        ctx.workers = 1
        ctx.worker_model = "thread"
        ctx.verbose = False
        return ctx

    def test_external_sink_is_used_and_not_stopped(self) -> None:
        from src.app.pipeline.execute import execute_phases

        ctx = self._ctx()
        external_sink = MagicMock()

        phase_state = MutablePhaseState()
        # No prefilter_skips so we exercise the simple "no Skipping phase" path
        # and only the per-phase iteration matters.
        phase_state.prefilter_skips = []

        with patch("src.app.pipeline.execute.run_all") as mock_run_all:
            mock_run_all.return_value = ({"success": 0, "skipped": 0, "failed": 0}, [], None, None)
            execute_phases(
                phases=[("Converting", [])],  # empty batch → early stop_phase
                ctx=ctx,
                phase_state=phase_state,
                sink=external_sink,
            )

        # start_phase / stop_phase must be driven on the external sink.
        assert external_sink.start_phase.called, "external sink.start_phase was not called"
        assert external_sink.stop_phase.called, "external sink.stop_phase was not called"
        # Critically: execute_phases must NOT take ownership and call .stop()
        # on a caller-owned sink. That would tear down the Live before the
        # caller (run_from_index) finishes print_summary().
        assert not external_sink.stop.called, (
            "execute_phases must NOT call sink.stop() on an externally-built sink"
        )

    def test_internal_sink_is_stopped_when_no_external_sink(self) -> None:
        """Without an external sink, execute_phases builds and tears down its
        own RichProgressSink — preserving the original behaviour for
        run_pipeline's call site."""
        from src.app.pipeline.execute import execute_phases

        ctx = self._ctx()

        phase_state = MutablePhaseState()
        phase_state.prefilter_skips = []

        captured_sink: list = []
        real_sink_class = "src.app.pipeline.execute.RichProgressSink"

        def _capture(**kwargs):
            m = MagicMock()
            captured_sink.append(m)
            return m

        with patch("src.app.pipeline.execute.run_all") as mock_run_all:
            mock_run_all.return_value = ({"success": 0, "skipped": 0, "failed": 0}, [], None, None)
            with patch(real_sink_class, side_effect=_capture) as mock_cls:
                execute_phases(
                    phases=[("Converting", [])],
                    ctx=ctx,
                    phase_state=phase_state,
                    sink=None,
                )

        # A sink was constructed by execute_phases itself.
        assert captured_sink, "execute_phases should build its own sink when sink=None"
        # And it must be stopped — that's the original lifecycle contract.
        assert captured_sink[0].stop.called, (
            "execute_phases should stop the internally-built sink on exit"
        )


# ---------------------------------------------------------------------------
# run_from_index threads one sink into prefilter + execute
# ---------------------------------------------------------------------------


class TestRunFromIndexThreadsOneSink:
    """``run_from_index.run`` must build a single sink and pass it to BOTH
    ``prefilter_jobs`` and ``execute_phases`` so the rich Live instance is
    shared across preverify → Skipping → Converting."""

    def _ctx_with_args(self, args_ns: MagicMock) -> MagicMock:
        from src.models.types import ExecutionMode

        ctx = MagicMock()
        ctx.args = args_ns
        # Mirror args.verbose onto ctx.verbose — run_from_index reads from ctx,
        # not args.
        ctx.verbose = bool(getattr(args_ns, "verbose", False))
        ctx.execution_mode = ExecutionMode.PHASED
        ctx.db_path = Path("/tmp/history.db")
        ctx.workers = 1
        ctx.worker_model = "thread"
        ctx.backend = MagicMock()
        ctx.preset = MagicMock()
        ctx.settings = MagicMock()
        ctx.settings.execution.probe_workers = 1
        return ctx

    def test_rich_sink_passed_to_prefilter_and_execute(self, tmp_path: Path) -> None:
        """When verbose=False, build a RichProgressSink and thread it through."""
        from src.app.commands.run_from_index import run as rfi_run

        args = MagicMock()
        args.index = tmp_path / "index.db"
        args.output = tmp_path / "out"
        args.preset = "flac"
        args.force = False
        args.lossy_action = "copy"
        args.no_lossy_check = True
        args.verbose = False
        args.execution_mode = "phased"
        args.verify_skip = False
        args.exclude = []
        args.playlist = None
        args.input = tmp_path

        ctx = self._ctx_with_args(args)

        rows = [
            MagicMock(
                source_path="C:/src1.flac",
                dest_path="D:/dst1.flac",
                job_type="convert",
                file_size=1024,
                sidecar_files="",
                mtime=0.0,
                is_lossy=False,
            )
        ]

        # Stub out everything except the sink-wiring observation point.
        fake_index_builder = MagicMock()
        # fake_index_builder is what IndexBuilder(...) returns. We also have
        # to wire .from_existing() (a classmethod) so the real call path
        # `IndexBuilder.from_existing(args.index)` resolves to our mock.
        fake_index_builder.iter_rows.side_effect = lambda: iter(rows)
        fake_index_builder.get_summary.return_value = {
            "total": 1, "lossy": 0, "total_bytes": 1024, "by_type": {"convert": 1},
        }
        fake_index_builder.close = MagicMock()

        # MagicMock factory: IndexBuilder(args.index) and
        # IndexBuilder.from_existing(args.index) both return fake_index_builder.
        fake_ib_cls = MagicMock(return_value=fake_index_builder)
        fake_ib_cls.from_existing.return_value = fake_index_builder

        jobs = [MagicMock(job_type="convert", infile=MagicMock(name="x.flac"), outfile=MagicMock())]
        for j in jobs:
            j.infile.name = "x.flac"

        captured: dict = {"prefilter_sink": None, "execute_sink": None}

        def _fake_prefilter_jobs(jobs_arg, ctx_arg, sink=None):
            captured["prefilter_sink"] = sink
            return ([], [])  # all skipped

        def _fake_execute_phases(phases, ctx_arg, phase_state, total_bytes=0, sink=None):
            captured["execute_sink"] = sink
            return ({"success": 0, "skipped": 0, "failed": 0}, None)

        # NOTE: build_jobs/prefilter_jobs/execute_phases/print_summary are
        # imported lazily inside run_from_index.run, so we must patch them at
        # their source modules — not as attributes of run_from_index. The
        # IndexBuilder import is at the top of run_from_index.py but the
        # package's __init__ shadows the submodule with a `run` function, so
        # we must reference the submodule via importlib to patch it.
        import importlib
        rfi_module = importlib.import_module("src.app.commands.run_from_index")
        with patch.object(rfi_module, "IndexBuilder", fake_ib_cls), \
             patch("src.app.pipeline.jobs.build_jobs", return_value=jobs), \
             patch("src.app.pipeline.prefilter.prefilter_jobs", side_effect=_fake_prefilter_jobs), \
             patch("src.app.pipeline.execute.execute_phases", side_effect=_fake_execute_phases), \
             patch("src.app.pipeline.reporting.print_summary"):
            rfi_run(ctx)

        # Both call sites must have received a sink instance.
        assert captured["prefilter_sink"] is not None, "prefilter_jobs was called without a sink"
        assert captured["execute_sink"] is not None, "execute_phases was called without a sink"

        # And it must be the SAME instance so one Live stays alive.
        assert captured["prefilter_sink"] is captured["execute_sink"], (
            "prefilter_jobs and execute_phases must receive the same sink instance "
            "so the rich progress Live is reused across preverify → execute."
        )

    def test_verbose_sink_passed_when_verbose(self, tmp_path: Path) -> None:
        """When verbose=True, build a VerboseProgressSink and thread it through."""
        from src.app.commands.run_from_index import run as rfi_run
        from src.ui.progress.verbose_sink import VerboseProgressSink

        args = MagicMock()
        args.index = tmp_path / "index.db"
        args.output = tmp_path / "out"
        args.preset = "flac"
        args.force = False
        args.lossy_action = "copy"
        args.no_lossy_check = True
        args.verbose = True
        args.execution_mode = "phased"
        args.verify_skip = False
        args.exclude = []
        args.playlist = None
        args.input = tmp_path

        ctx = self._ctx_with_args(args)

        rows = [
            MagicMock(
                source_path="C:/src1.flac",
                dest_path="D:/dst1.flac",
                job_type="convert",
                file_size=1024,
                sidecar_files="",
                mtime=0.0,
                is_lossy=False,
            )
        ]

        fake_index_builder = MagicMock()
        fake_index_builder.iter_rows.side_effect = lambda: iter(rows)
        fake_index_builder.get_summary.return_value = {
            "total": 1, "lossy": 0, "total_bytes": 1024, "by_type": {"convert": 1},
        }
        fake_index_builder.close = MagicMock()

        # MagicMock factory: IndexBuilder(args.index) and
        # IndexBuilder.from_existing(args.index) both return fake_index_builder.
        fake_ib_cls = MagicMock(return_value=fake_index_builder)
        fake_ib_cls.from_existing.return_value = fake_index_builder

        jobs = [MagicMock(job_type="convert", infile=MagicMock(name="x.flac"), outfile=MagicMock())]
        for j in jobs:
            j.infile.name = "x.flac"

        captured: dict = {"prefilter_sink": None, "execute_sink": None}

        def _fake_prefilter_jobs(jobs_arg, ctx_arg, sink=None):
            captured["prefilter_sink"] = sink
            return ([], [])

        def _fake_execute_phases(phases, ctx_arg, phase_state, total_bytes=0, sink=None):
            captured["execute_sink"] = sink
            return ({"success": 0, "skipped": 0, "failed": 0}, None)

        import importlib
        rfi_module = importlib.import_module("src.app.commands.run_from_index")
        with patch.object(rfi_module, "IndexBuilder", fake_ib_cls), \
             patch("src.app.pipeline.jobs.build_jobs", return_value=jobs), \
             patch("src.app.pipeline.prefilter.prefilter_jobs", side_effect=_fake_prefilter_jobs), \
             patch("src.app.pipeline.execute.execute_phases", side_effect=_fake_execute_phases), \
             patch("src.app.pipeline.reporting.print_summary"):
            rfi_run(ctx)

        # Verbose mode gets a VerboseProgressSink.
        assert isinstance(captured["prefilter_sink"], VerboseProgressSink)
        assert isinstance(captured["execute_sink"], VerboseProgressSink)
        assert captured["prefilter_sink"] is captured["execute_sink"]


# ---------------------------------------------------------------------------
# Sanity: the RichProgressSink default-construct path still works after the
# IndexBuilder is closed (run_from_index closes it before prefilter runs).
# ---------------------------------------------------------------------------


class TestRichSinkConstructible:
    """Sanity check: a RichProgressSink built with total_files/total_bytes
    can start a phase, advance, and stop_phase without raising."""

    def test_lifecycle_smoke(self) -> None:
        from src.ui.progress.rich_sink import RichProgressSink

        sink = RichProgressSink(total_files=100, total_bytes=1_000_000)
        try:
            sink.start_phase("Pre-verifying 100 files", total=100)
            sink.set_activity("verifying")
            for _ in range(100):
                sink.advance()
            sink.set_counters(demoted=0, kept=100)
            sink.log("[preverify] 100 checked, 0 demoted, 100 kept")
            sink.stop_phase()

            sink.start_phase("Converting", total=0)
            sink.stop_phase()
        finally:
            sink.stop()