"""tests/test_progress_view.py: Tests for ProgressSink, RichProgressSink, scan_with_progress, and _drain_events_into_ui."""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from src.execution.runner import _drain_events_into_ui, run_all
from src.index.scanner import scan_with_progress
from src.models.types import Backend, BackendPresetArgs, ConversionJob, PresetConfig
from src.ui.progress_view import ProgressSink, RichProgressSink, SubtaskID


# ---------------------------------------------------------------------------
# Recording test double
# ---------------------------------------------------------------------------


class RecordingProgressSink:
    """Test double that records every method call as (method_name, args, kwargs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append((method, args, kwargs))

    def start_phase(self, name: str, total: int) -> None:
        self._record("start_phase", (name, total), {})

    def advance(self, amount: int = 1) -> None:
        self._record("advance", (amount,), {})

    def start_subtask(self, name: str) -> SubtaskID:
        subtask_id = SubtaskID(len(self.calls))
        self._record("start_subtask", (name, subtask_id), {})
        return subtask_id

    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        self._record("finish_subtask", (subtask_id,), {})

    def log(self, message: str) -> None:
        self._record("log", (message,), {})

    def stop(self) -> None:
        self._record("stop", (), {})

    def stop_phase(self) -> None:
        self._record("stop_phase", (), {})

    def set_activity(self, activity: str) -> None:
        self._record("set_activity", (activity,), {})

    def set_phase_label(self, label: str) -> None:
        self._record("set_phase_label", (label,), {})

    def log_verify_result(
        self,
        infile: str,
        status: str,
        reason: str | None,
        fmt: str | None,
        duration_s: float | None,
    ) -> None:
        self._record(
            "log_verify_result",
            (infile, status, reason, fmt, duration_s),
            {},
        )

    def log_convert_result(
        self,
        infile: str,
        outfile: str,
        encoder: str,
        output_bytes: int | None,
        elapsed_s: float,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        self._record(
            "log_convert_result",
            (infile, outfile, encoder, output_bytes, elapsed_s, status, error_msg),
            {},
        )

    def set_counters(self, demoted: int = 0, kept: int = 0) -> None:
        self._record("set_counters", (demoted, kept), {})


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------


def test_scan_with_progress_records_advances(
    tmp_path: Path,
) -> None:
    """scan_with_progress calls advance() once per discovered file (no start_phase in current impl)."""
    (tmp_path / "a.flac").touch()
    (tmp_path / "b.mp3").touch()
    (tmp_path / "c.m4a").touch()

    sink = RecordingProgressSink()
    rows, _ = scan_with_progress(tmp_path, [], None, sink)

    assert len(rows) == 3

    method_names = [call[0] for call in sink.calls]
    advance_calls = [c for c in sink.calls if c[0] == "advance"]
    assert len(advance_calls) == 3
    for ac in advance_calls:
        assert ac[1] == (1,)
    # scan_with_progress does not call start_phase in the current implementation
    assert "start_phase" not in method_names


def test_scan_with_progress_zero_files(tmp_path: Path) -> None:
    """No advance() calls when no audio files are found."""
    sink = RecordingProgressSink()
    rows, _ = scan_with_progress(tmp_path, [], None, sink)

    assert len(rows) == 0
    # Current scanner impl: only advance() per file, no start_phase
    assert "start_phase" not in [c[0] for c in sink.calls]


# ---------------------------------------------------------------------------
# _drain_events_into_ui routing tests
# ---------------------------------------------------------------------------


def test_drain_routes_started_to_start_subtask() -> None:
    """STARTED event causes start_subtask to be called on the sink."""
    from src.execution.runner import JobEventKind

    events: Queue = Queue()
    events.put((JobEventKind.STARTED, "file1.flac"))
    events.put((JobEventKind.FINISHED, "file1.flac"))

    sink = RecordingProgressSink()
    job_tasks: dict = {}
    _drain_events_into_ui(events, sink, job_tasks)

    methods = [c[0] for c in sink.calls]
    assert "start_subtask" in methods
    assert "finish_subtask" in methods
    # start_subtask now records (name, subtask_id)
    assert sink.calls[0][0] == "start_subtask"
    assert sink.calls[0][1][0] == "file1.flac"
    # second call is finish_subtask
    assert sink.calls[1][0] == "finish_subtask"


def test_drain_routes_log_to_log() -> None:
    """LOG event causes log to be called with the message."""
    from src.execution.runner import JobEventKind

    events: Queue = Queue()
    events.put((JobEventKind.LOG, "Encoding progress: 50%"))

    sink = RecordingProgressSink()
    job_tasks: dict = {}
    _drain_events_into_ui(events, sink, job_tasks)

    assert sink.calls == [("log", ("Encoding progress: 50%",), {})]


def test_drain_multiple_inflight_jobs_ordered() -> None:
    """Multiple STARTED before FINISHED produces interleaved start/finish calls."""
    from src.execution.runner import JobEventKind

    events: Queue = Queue()
    events.put((JobEventKind.STARTED, "a.flac"))
    events.put((JobEventKind.STARTED, "b.mp3"))
    events.put((JobEventKind.FINISHED, "a.flac"))
    events.put((JobEventKind.FINISHED, "b.mp3"))

    sink = RecordingProgressSink()
    job_tasks: dict = {}
    _drain_events_into_ui(events, sink, job_tasks)

    methods = [c[0] for c in sink.calls]
    # Each job produces: start_subtask, finish_subtask, advance
    assert methods == [
        "start_subtask",
        "start_subtask",
        "finish_subtask",
        "advance",
        "finish_subtask",
        "advance",
    ]
    # Verify each finish_subtask received the SubtaskID from its matching start_subtask
    start_calls = [c for c in sink.calls if c[0] == "start_subtask"]
    finish_calls = [c for c in sink.calls if c[0] == "finish_subtask"]
    assert len(finish_calls) == len(start_calls)
    for sc, fc in zip(start_calls, finish_calls):
        # sc[1] = (name, subtask_id) — the subtask_id is the second element
        start_sid = sc[1][1]
        # fc[1] = (subtask_id,)
        finish_sid = fc[1][0]
        assert finish_sid is start_sid


def test_drain_unknown_event_kind_silent() -> None:
    """Unknown JobEventKind does not call any sink method (queue drains silently)."""
    events: Queue = Queue()
    events.put(("UNKNOWN", "file1.flac"))

    sink = RecordingProgressSink()
    job_tasks: dict = {}
    _drain_events_into_ui(events, sink, job_tasks)

    assert sink.calls == []


# ---------------------------------------------------------------------------
# SubtaskID round-trip identity test
# ---------------------------------------------------------------------------


def test_subtask_id_roundtrip_preserves_identity() -> None:
    """SubtaskID returned from start_subtask is the same object accepted by finish_subtask."""
    sink = RecordingProgressSink()
    subtask_id = sink.start_subtask("my-job.mp3")

    sink.finish_subtask(subtask_id)

    # sink.calls[0] = ("start_subtask", ("my-job.mp3", subtask_id), {})
    # sink.calls[1] = ("finish_subtask", (subtask_id,), {})
    assert sink.calls[0][1] == ("my-job.mp3", subtask_id)
    assert sink.calls[1][1] == (subtask_id,)
    assert sink.calls[1][1][0] is subtask_id


# ---------------------------------------------------------------------------
# Process-pool picklability regression tests
# ---------------------------------------------------------------------------


def test_direct_print_callback_is_picklable() -> None:
    """The verbose-mode stream callback must be picklable for ProcessPoolExecutor.

    Regression: ``_direct_print_callback`` was previously a local function
    nested inside ``run_all``. Local functions are not picklable on
    Windows spawn-based multiprocessing, which is the default, and the
    worker submission would fail with::

        _pickle.PicklingError: Can't pickle local object
        <function run_all.<locals>._direct_print_callback ...>
    """
    import pickle

    from src.execution.events import _direct_print_callback

    # Module-level function — pickle must succeed.
    pickled = pickle.dumps(_direct_print_callback)
    restored = pickle.loads(pickled)
    assert restored is _direct_print_callback


def test_run_all_verbose_process_workers_does_not_pickle_error(
    stub_db: Any,
    stub_preset: PresetConfig,
    tmp_path: Path,
) -> None:
    """``run_all`` with verbose=True + process workers must succeed end-to-end.

    Regression: ``--verbose --worker-model process`` previously crashed with
    a ``PicklingError`` on the very first job because the verbose stream
    callback was a local function inside ``run_all``.
    """
    src = tmp_path / "a.flac"
    src.touch()
    job = ConversionJob(
        infile=src,
        outfile=tmp_path / "a_out.flac",
        preset=stub_preset,
        job_type="convert",
    )

    backend = _StubBackend([])
    sink = RecordingProgressSink()

    summary, _futures, _events, write_queue = run_all(
        jobs=[job],
        backend=backend,
        db_path=str(stub_db.db_path),
        force=True,
        workers=2,
        worker_model="process",
        verbose=True,
        print_to_terminal=True,
        progress=sink,
    )

    write_queue.flush()
    # Total counts must equal jobs submitted.
    assert summary["success"] + summary["failed"] + summary["skipped"] == 1


# ---------------------------------------------------------------------------
# RichProgressSink.stop() safety tests
# ---------------------------------------------------------------------------


def test_rich_stop_without_start_is_safe() -> None:
    """stop() on a RichProgressSink that never had start_phase() called does not raise."""
    sink = RichProgressSink()
    sink.stop()
    sink.stop()


def test_rich_stop_before_start_is_safe() -> None:
    """stop() called before start_phase() does not raise."""
    sink = RichProgressSink()
    sink.stop()
    sink.start_phase("Scanning", 5)
    sink.stop()


def test_rich_stop_after_start_is_safe() -> None:
    """stop() after start_phase() completes is safe."""
    sink = RichProgressSink()
    sink.start_phase("Scanning", 3)
    sink.advance()
    sink.advance()
    sink.stop()


def test_rich_double_stop_is_safe() -> None:
    """Calling stop() twice is safe."""
    sink = RichProgressSink()
    sink.start_phase("Scanning", 2)
    sink.stop()
    sink.stop()


# ---------------------------------------------------------------------------
# run_all stubbed backend tests
# ---------------------------------------------------------------------------


class _StubBackend:
    """Minimal ConversionBackend stub that pushes fixed events and returns fixed results."""

    def name(self) -> Backend:
        return Backend.NATIVE_FFMPEG

    def supports(self, preset: PresetConfig) -> bool:
        return True

    def validate_environment(self) -> None:
        pass

    def __init__(self, events: list[tuple[Any, Any]], status: str = "SUCCESS") -> None:
        self._events = events
        self._status: str = status

    def run(
        self, job: ConversionJob, stream_callback: Any = None
    ) -> Any:
        from src.models.types import JobResult

        if job.job_type == "skip":
            return JobResult(job=job, status="SKIPPED")
        # Materialise an output file so the post-write verifier's existence
        # check has something to act on. Try to write a tiny but valid audio
        # file (FLAC for .flac/.ogg/.opus outputs, a real MP3 frame for .mp3)
        # so the verifier reports OK; fall back to harmless bytes for
        # anything we can't write. Tests that don't care about the verify
        # step just need existence + non-empty size.
        if job.job_type in ("convert", "copy") and job.outfile is not None:
            job.outfile.parent.mkdir(parents=True, exist_ok=True)
            try:
                import numpy as np
                import soundfile as sf

                data = np.zeros(2205, dtype=np.float32)  # 50ms silence
                sf.write(str(job.outfile), data, 44100)
            except Exception:
                job.outfile.write_bytes(b"\x00" * 16)
        return JobResult(job=job, status=self._status)


@pytest.fixture
def stub_db(tmp_path: Path) -> Any:
    """Create an in-memory ConversionDB backed by a temp file."""
    from src.history.db import ConversionDB

    db_path = tmp_path / "test_history.db"
    db = ConversionDB(db_path)
    return db


@pytest.fixture
def stub_preset() -> PresetConfig:
    """Minimal PresetConfig."""
    return PresetConfig(
        name="test",
        ext="flac",
        backends={Backend.NATIVE_FFMPEG: BackendPresetArgs(tool="ffmpeg")},
    )


def test_run_all_single_worker_produces_expected_sink_sequence(
    stub_db: Any,
    stub_preset: PresetConfig,
    tmp_path: Path,
) -> None:
    """run_all with workers=1 produces advance() for each job completion."""
    audio_file = tmp_path / "a.flac"
    audio_file.touch()

    job = ConversionJob(
        infile=audio_file,
        outfile=tmp_path / "a_out.flac",
        preset=stub_preset,
        job_type="convert",
    )

    backend = _StubBackend([])
    sink = RecordingProgressSink()

    summary, futures, _events, write_queue = run_all(
        jobs=[job],
        backend=backend,
        db_path=str(stub_db.db_path),
        force=False,
        workers=1,
        worker_model="thread",
        verbose=False,
        progress=sink,
    )

    write_queue.flush()
    assert summary["success"] == 1
    advance_calls = [c for c in sink.calls if c[0] == "advance"]
    assert len(advance_calls) == 1


def test_run_all_parallel_worker_produces_events(
    stub_db: Any,
    stub_preset: PresetConfig,
    tmp_path: Path,
) -> None:
    """run_all with workers=2 returns events queue that can be drained."""
    audio_a = tmp_path / "a.flac"
    audio_b = tmp_path / "b.flac"
    audio_a.touch()
    audio_b.touch()

    job_a = ConversionJob(
        infile=audio_a,
        outfile=tmp_path / "a_out.flac",
        preset=stub_preset,
        job_type="convert",
    )
    job_b = ConversionJob(
        infile=audio_b,
        outfile=tmp_path / "b_out.flac",
        preset=stub_preset,
        job_type="convert",
    )

    backend = _StubBackend([])
    sink = RecordingProgressSink()

    _summary, _futures, events, write_queue = run_all(
        jobs=[job_a, job_b],
        backend=backend,
        db_path=str(stub_db.db_path),
        force=False,
        workers=2,
        worker_model="thread",
        verbose=False,
        progress=sink,
    )

    import time

    start = time.monotonic()
    while time.monotonic() - start < 2.0:
        if not events.empty():
            break
        time.sleep(0.01)
    _drain_events_into_ui(events, sink, {})

    write_queue.flush()
    methods = [c[0] for c in sink.calls]
    assert "start_subtask" in methods
    assert "finish_subtask" in methods


def test_run_all_parallel_worker_counts_results(
    stub_db: Any,
    stub_preset: PresetConfig,
    tmp_path: Path,
) -> None:
    """Regression: run_all must count SUCCESS/FAILED regardless of worker count.

    Previously, ``run_all`` only iterated ``as_completed`` futures when
    ``workers == 1``, which silently left the summary at ``{0, 0, 0}``
    for parallel runs — masking failures in verbose mode.
    """
    jobs = []
    for i in range(4):
        src = tmp_path / f"a{i}.flac"
        src.touch()
        jobs.append(
            ConversionJob(
                infile=src,
                outfile=tmp_path / f"a{i}_out.flac",
                preset=stub_preset,
                job_type="convert",
            )
        )

    backend = _StubBackend([])
    sink = RecordingProgressSink()

    summary, _futures, _events, write_queue = run_all(
        jobs=jobs,
        backend=backend,
        db_path=str(stub_db.db_path),
        force=True,  # bypass resume checks — they may have been recorded by an earlier test
        workers=4,
        worker_model="thread",
        verbose=False,
        progress=sink,
    )

    write_queue.flush()
    # All four jobs ran (force=True bypasses resume). With workers=4 the
    # summary must NOT be silently zero — that was the original bug. The
    # outcome (success vs failed) depends on the verifier's behaviour on
    # the stub file, which is irrelevant to this test.
    assert summary["success"] + summary["failed"] + summary["skipped"] == 4, (
        f"run_all dropped results: summary={summary}, expected total 4"
    )


def test_run_all_parallel_emits_convert_result_to_sink(
    stub_db: Any,
    stub_preset: PresetConfig,
    tmp_path: Path,
) -> None:
    """Verbose mode: each completed job produces a ``log_convert_result`` call.

    Regression: with workers > 1 the drain thread must still forward
    ``CONVERT_RESULT`` events to the sink so the user sees per-file
    convert lines like ``convert SUCCESS 12.34s 47.2 MiB ALAC …``.
    """
    src = tmp_path / "a.flac"
    src.touch()
    job = ConversionJob(
        infile=src,
        outfile=tmp_path / "a_out.flac",
        preset=stub_preset,
        job_type="convert",
    )

    backend = _StubBackend([])
    sink = RecordingProgressSink()

    run_all(
        jobs=[job],
        backend=backend,
        db_path=str(stub_db.db_path),
        force=False,
        workers=2,
        worker_model="thread",
        verbose=False,
        progress=sink,
    )

    # The drain thread runs in the background and processes events; the
    # run_all() finally block joins it, then drains once more. Give it a
    # tiny grace window in case the join races the queue.
    import time

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        convert_calls = [c for c in sink.calls if c[0] == "log_convert_result"]
        if convert_calls:
            break
        time.sleep(0.01)

    convert_calls = [c for c in sink.calls if c[0] == "log_convert_result"]
    assert convert_calls, f"expected log_convert_result, got calls: {[c[0] for c in sink.calls]}"
    # Payload is (infile, outfile, encoder, output_bytes, elapsed_s, status, error_msg)
    payload = convert_calls[0][1]
    assert payload[5] == "SUCCESS"


def test_run_all_empty_job_list(stub_db: Any) -> None:
    """run_all with an empty jobs list returns zero summary and empty events."""
    backend = _StubBackend([])
    sink = RecordingProgressSink()

    summary, futures, events, write_queue = run_all(
        jobs=[],
        backend=backend,
        db_path=str(stub_db.db_path),
        force=False,
        workers=1,
        worker_model="thread",
        verbose=False,
        progress=sink,
    )

    write_queue.flush()
    assert summary == {"success": 0, "skipped": 0, "failed": 0}
    assert futures == []
    assert sink.calls == []


def test_rich_progress_sink_protocol_compliance() -> None:
    """RichProgressSink satisfies the ProgressSink Protocol."""
    sink: ProgressSink = RichProgressSink()
    sink.start_phase("Scanning", 10)
    sink.advance(2)
    subtask = sink.start_subtask("job1")
    sink.finish_subtask(subtask)
    sink.log("test message")
    sink.stop()
