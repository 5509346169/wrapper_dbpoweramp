"""tests/test_failed_only.py: Tests for the --failed-only prefilter branch + bulk DB query.

The flag restricts the pipeline to files whose latest history row is FAILED;
everything else is skipped without further inspection. Tests cover:

  - ConversionDB.failed_job_pairs(): SELECT FAILED triples, plus the
    SUCCESS-after-FAILED / FAILED-after-SUCCESS round-trip semantics (the
    schema's UNIQUE(source_path, dest_path) plus INSERT OR REPLACE means a
    newer attempt replaces the older row in place).
  - prefilter_jobs() with --failed-only=True: matched jobs → pending,
    unmatched → skipped, regardless of force / verify_skip / should_skip.
  - args.validate_args() mutex: --failed-only + --force fails fast.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.types import ConversionJob


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)


def _make_job(infile: str, outfile: Path, job_type: str = "convert") -> ConversionJob:
    return ConversionJob(
        infile=Path(infile),
        outfile=outfile,
        preset=MagicMock(),
        job_type=job_type,
    )


# ── ConversionDB.failed_job_pairs() ────────────────────────────────────────


class TestFailedJobPairs:
    """The bulk query must return only (source, dest, job_type) triples whose
    *latest* history row is FAILED. A SUCCESS retry on the same triple must
    drop the pair from the set."""

    def _seed_history(self, db_path: Path, rows: list[tuple]) -> None:
        """Insert rows into the history table directly.

        Each tuple is (source_path, dest_path, job_type, status, timestamp).
        ``timestamp`` is compared lexicographically; the test must supply
        monotonically increasing strings to simulate chronological order.

        Opens + closes ``ConversionDB`` first so the schema (and migrations)
        run before we touch the file with raw sqlite3.
        """
        bootstrap = self._open_db(db_path)
        bootstrap.close()
        conn = sqlite3.connect(str(db_path))
        try:
            for src, dst, jtype, status, ts in rows:
                conn.execute(
                    "INSERT INTO history (source_path, dest_path, job_type, "
                    "status, command, timestamp) VALUES (?, ?, ?, ?, NULL, ?)",
                    (src, dst, jtype, status, ts),
                )
            conn.commit()
        finally:
            conn.close()

    def _open_db(self, db_path: Path):
        from src.history.conversion_db import ConversionDB

        return ConversionDB(db_path)

    def test_empty_db_returns_empty_set(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        # ConversionDB constructor calls migrate_to_current which creates the
        # table — call it so the schema exists.
        db = self._open_db(db_path)
        try:
            assert db.failed_job_pairs() == set()
        finally:
            db.close()

    def test_only_failed_returns_triple(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        self._seed_history(
            db_path,
            [
                ("/a.flac", "/a.mp3", "convert", "FAILED", "2026-01-01T00:00:00+00:00"),
            ],
        )
        db = self._open_db(db_path)
        try:
            result = db.failed_job_pairs(("convert",))
            assert result == {("/a.flac", "/a.mp3", "convert")}
        finally:
            db.close()

    def test_success_after_failure_drops_pair(self, tmp_path: Path) -> None:
        """When the wrapper retries a previously-failed (src, dst) and it
        succeeds, the FAILED row is replaced by a SUCCESS row — so the
        failed set no longer contains that pair."""
        db_path = tmp_path / "history.db"
        # Seed: insert FAILED row, then INSERT OR REPLACE with SUCCESS at
        # the same (src, dst) — this is exactly what ConversionDB.log_conversion
        # does when a retry succeeds.
        bootstrap = self._open_db(db_path)
        bootstrap.close()
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO history (source_path, dest_path, job_type, "
                "status, command, timestamp) VALUES (?, ?, ?, ?, NULL, ?)",
                ("/a.flac", "/a.mp3", "convert", "FAILED", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO history (source_path, dest_path, job_type, "
                "status, command, timestamp) VALUES (?, ?, ?, ?, NULL, ?)",
                ("/a.flac", "/a.mp3", "convert", "SUCCESS", "2026-02-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        db = self._open_db(db_path)
        try:
            # SUCCESS row replaced FAILED; pair is no longer in the failed set.
            assert db.failed_job_pairs(("convert",)) == set()
        finally:
            db.close()

    def test_failure_after_success_keeps_pair(self, tmp_path: Path) -> None:
        """A subsequent FAILED retry (after a SUCCESS) overwrites the row —
        so the pair reappears in the failed set."""
        db_path = tmp_path / "history.db"
        bootstrap = self._open_db(db_path)
        bootstrap.close()
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO history (source_path, dest_path, job_type, "
                "status, command, timestamp) VALUES (?, ?, ?, ?, NULL, ?)",
                ("/a.flac", "/a.mp3", "convert", "SUCCESS", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO history (source_path, dest_path, job_type, "
                "status, command, timestamp) VALUES (?, ?, ?, ?, NULL, ?)",
                ("/a.flac", "/a.mp3", "convert", "FAILED", "2026-02-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        db = self._open_db(db_path)
        try:
            result = db.failed_job_pairs(("convert",))
            assert result == {("/a.flac", "/a.mp3", "convert")}
        finally:
            db.close()

    def test_filter_by_job_type(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        self._seed_history(
            db_path,
            [
                ("/a.flac", "/a.mp3", "convert", "FAILED", "2026-01-01T00:00:00+00:00"),
                ("/b.flac", "/b.flac", "copy",    "FAILED", "2026-01-02T00:00:00+00:00"),
                ("/c.flac", "/c.flac", "skip",    "FAILED", "2026-01-03T00:00:00+00:00"),
            ],
        )
        db = self._open_db(db_path)
        try:
            # Default: convert + copy.
            assert db.failed_job_pairs() == {
                ("/a.flac", "/a.mp3", "convert"),
                ("/b.flac", "/b.flac", "copy"),
            }
            # Only convert.
            assert db.failed_job_pairs(("convert",)) == {
                ("/a.flac", "/a.mp3", "convert"),
            }
            # Custom tuple that excludes skip anyway.
            assert db.failed_job_pairs(("convert", "copy", "skip")) == {
                ("/a.flac", "/a.mp3", "convert"),
                ("/b.flac", "/b.flac", "copy"),
                ("/c.flac", "/c.flac", "skip"),
            }
        finally:
            db.close()

    def test_empty_job_types_returns_empty_set(self, tmp_path: Path) -> None:
        db_path = tmp_path / "history.db"
        self._seed_history(
            db_path,
            [
                ("/a.flac", "/a.mp3", "convert", "FAILED", "2026-01-01T00:00:00+00:00"),
            ],
        )
        db = self._open_db(db_path)
        try:
            assert db.failed_job_pairs(()) == set()
        finally:
            db.close()


# ── prefilter_jobs() --failed-only branch ─────────────────────────────────


class TestFailedOnlyPrefilter:
    """When --failed-only is set, only jobs in the failed set go pending."""

    def test_matched_job_goes_pending_unmatched_goes_skipped(self) -> None:
        from src.app.pipeline.prefilter import prefilter_jobs

        out_a = _closed_temp_file(".flac", b"x")
        out_b = _closed_temp_file(".flac", b"y")
        try:
            job_a = _make_job("/src_a.flac", out_a)
            job_b = _make_job("/src_b.flac", out_b)

            mock_db = MagicMock()
            mock_db.failed_job_pairs.return_value = {
                (str(job_a.infile), str(job_a.outfile), "convert"),
            }

            mock_args = MagicMock()
            mock_args.failed_only = True
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = True

            mock_sink = MagicMock()

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                pending, skipped = prefilter_jobs(
                    [job_a, job_b], mock_ctx, sink=mock_sink,
                )

            assert pending == [job_a]
            assert skipped == [job_b]
            # Even though --force is False, the resume-cache check must be
            # bypassed entirely when --failed-only is in effect.
            mock_db.should_skip.assert_not_called()
        finally:
            out_a.unlink(missing_ok=True)
            out_b.unlink(missing_ok=True)

    def test_empty_failed_set_skips_everything(self) -> None:
        from src.app.pipeline.prefilter import prefilter_jobs

        out = _closed_temp_file(".flac", b"x")
        try:
            job = _make_job("/src.flac", out)

            mock_db = MagicMock()
            mock_db.failed_job_pairs.return_value = set()

            mock_args = MagicMock()
            mock_args.failed_only = True
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                pending, skipped = prefilter_jobs([job], mock_ctx)

            assert pending == []
            assert skipped == [job]
        finally:
            out.unlink(missing_ok=True)

    def test_failed_only_bypasses_resume_cache(self) -> None:
        """A previously-SUCCESS job whose (src,dst,job_type) is in the failed
        set must still go pending — the resume-cache check is irrelevant
        under --failed-only."""
        from src.app.pipeline.prefilter import prefilter_jobs

        out = _closed_temp_file(".flac", b"x")
        try:
            job = _make_job("/src.flac", out)

            mock_db = MagicMock()
            mock_db.failed_job_pairs.return_value = {
                (str(job.infile), str(job.outfile), "convert"),
            }

            mock_args = MagicMock()
            mock_args.failed_only = True
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                pending, skipped = prefilter_jobs([job], mock_ctx)

            assert pending == [job]
            assert skipped == []
        finally:
            out.unlink(missing_ok=True)

    def test_failed_only_emits_phase_bar(self) -> None:
        """The sink must receive start_phase + advance + stop_phase so the
        user sees a visible 'Filtering to failed-only' bar."""
        from src.app.pipeline.prefilter import prefilter_jobs

        out_a = _closed_temp_file(".flac", b"x")
        out_b = _closed_temp_file(".flac", b"y")
        try:
            job_a = _make_job("/src_a.flac", out_a)
            job_b = _make_job("/src_b.flac", out_b)

            mock_db = MagicMock()
            mock_db.failed_job_pairs.return_value = {
                (str(job_a.infile), str(job_a.outfile), "convert"),
            }

            mock_args = MagicMock()
            mock_args.failed_only = True
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = True

            mock_sink = MagicMock()

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                prefilter_jobs([job_a, job_b], mock_ctx, sink=mock_sink)

            mock_sink.start_phase.assert_called_once()
            phase_name = mock_sink.start_phase.call_args.args[0]
            assert "failed" in phase_name.lower()
            assert mock_sink.start_phase.call_args.kwargs["total"] == 2
            assert mock_sink.advance.call_count == 2
            mock_sink.stop_phase.assert_called_once()
            # Summary line emitted.
            log_lines = [c.args[0] for c in mock_sink.log.call_args_list]
            assert any("1 previously-failed" in m for m in log_lines)
        finally:
            out_a.unlink(missing_ok=True)
            out_b.unlink(missing_ok=True)

    def test_failed_only_includes_copy_jobs(self) -> None:
        """A failed copy job must also be retried when --failed-only is set."""
        from src.app.pipeline.prefilter import prefilter_jobs

        out = _closed_temp_file(".flac", b"x")
        try:
            job = _make_job("/src.flac", out, job_type="copy")

            mock_db = MagicMock()
            mock_db.failed_job_pairs.return_value = {
                (str(job.infile), str(job.outfile), "copy"),
            }

            mock_args = MagicMock()
            mock_args.failed_only = True
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = True

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                pending, skipped = prefilter_jobs([job], mock_ctx)

            assert pending == [job]
            assert skipped == []
        finally:
            out.unlink(missing_ok=True)

    def test_normal_prefilter_unaffected_when_flag_off(self) -> None:
        """Sanity check: when failed_only is False, the original resume-cache
        path runs (verified via should_skip being called)."""
        from src.app.pipeline.prefilter import prefilter_jobs

        out = _closed_temp_file(".flac", b"x")
        try:
            job = _make_job("/src.flac", out)

            mock_db = MagicMock()
            mock_db.should_skip.return_value = True

            mock_args = MagicMock()
            mock_args.failed_only = False
            mock_args.force = False
            mock_args.verify_skip = False

            mock_ctx = MagicMock()
            mock_ctx.args = mock_args
            mock_ctx.db_path = Path("/tmp/history.db")
            mock_ctx.failed_only = False

            with patch("src.app.pipeline.prefilter.ConversionDB", return_value=mock_db):
                pending, skipped = prefilter_jobs([job], mock_ctx)

            assert skipped == [job]
            assert pending == []
            mock_db.failed_job_pairs.assert_not_called()
        finally:
            out.unlink(missing_ok=True)


# ── args.validate_args() mutex ─────────────────────────────────────────────


class TestFailedOnlyArgparse:
    """CLI parsing + cross-flag validation for --failed-only."""

    def test_default_failed_only_is_none(self) -> None:
        from src.cli.args import parse_args

        args = parse_args([
            "-I", "/in", "-O", "/out", "-p", "flac-lossless",
        ])
        # None (not False) so build_context can collapse to False.
        assert args.failed_only is None

    def test_flag_sets_true(self) -> None:
        from src.cli.args import parse_args

        args = parse_args([
            "-I", "/in", "-O", "/out", "-p", "flac-lossless",
            "--failed-only",
        ])
        assert args.failed_only is True

    def test_no_flag_sets_false(self) -> None:
        from src.cli.args import parse_args

        args = parse_args([
            "-I", "/in", "-O", "/out", "-p", "flac-lossless",
            "--no-failed-only",
        ])
        assert args.failed_only is False

    def test_force_with_failed_only_rejected(self, capsys) -> None:
        from src.cli.args import parse_args, validate_args

        args = parse_args([
            "-I", "/in", "-O", "/out", "-p", "flac-lossless",
            "--force", "--failed-only",
        ])
        with pytest.raises(SystemExit) as exc:
            validate_args(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err

    def test_help_text_mentions_overwrite(self, capfd) -> None:
        """The user explicitly asked that --failed-only also overwrite the
        output. The help text must call this out so future users understand
        the side effect."""
        from src.cli.args import parse_args

        with pytest.raises(SystemExit):
            # argparse exits with code 0 on --help; pytest.raises(SystemExit)
            # catches it so the test can assert after.
            parse_args(["--failed-only", "--help"])
        # argparse writes help via print_help() which goes to sys.stdout
        # (file descriptor 1) — capsys won't capture it, capfd does.
        captured = capfd.readouterr()
        assert "overwrit" in captured.out.lower()