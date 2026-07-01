"""tests/test_conversion_db.py: Tests for ConversionDB.should_skip."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path) -> object:
    """In-memory ConversionDB backed by a temp file."""
    from src.history.db import ConversionDB

    db_path = tmp_path / "test_history.db"
    return ConversionDB(db_path)


class TestConversionDBShouldSkip:
    """Coverage for ConversionDB.should_skip scenarios."""

    def test_no_record_returns_false(self, db: object) -> None:
        """No matching record -> should_skip returns False."""
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is False

    def test_failed_record_returns_false(self, db: object) -> None:
        """A FAILED record -> should_skip returns False."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="FAILED",
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is False

    def test_success_no_dest_returns_false(self, db: object) -> None:
        """SUCCESS record but dest_file_exists=False -> should_skip returns False."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=False,
            dest_file_size=None,
        ) is False

    def test_success_with_dest_returns_true(self, db: object) -> None:
        """SUCCESS record with matching dest -> should_skip returns True."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is True

    def test_job_type_mismatch_returns_false(self, db: object) -> None:
        """A SUCCESS 'copy' record does not skip a 'convert' job."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.mp3",
            job_type="copy",
            command=None,
            status="SUCCESS",
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.mp3",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is False

    def test_source_path_mismatch_returns_false(self, db: object) -> None:
        """A record with a different source path does not skip."""
        db.log_conversion(
            source="D:/src/other.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is False

    def test_file_size_mismatch_returns_false(self, db: object) -> None:
        """A SUCCESS record exists but current dest size differs from stored size -> should_skip returns False."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
            file_size=1024,
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=2048,
        ) is False

    def test_file_size_match_returns_true(self, db: object) -> None:
        """A SUCCESS record with matching dest size -> should_skip returns True."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
            file_size=1024,
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=1024,
        ) is True

    def test_file_size_none_dest_none_returns_true(self, db: object) -> None:
        """SUCCESS record with no stored size and dest_size=None -> should_skip returns True."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
            file_size=None,
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is True

    def test_file_size_stored_none_dest_provided_returns_true(self, db: object) -> None:
        """SUCCESS record with no stored size but dest_size provided -> should_skip returns True (no check possible)."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
            file_size=None,
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is True

    def test_file_size_dest_provided_stored_none_returns_true(self, db: object) -> None:
        """SUCCESS record with stored size but no dest_size provided -> should_skip returns True (no check possible)."""
        db.log_conversion(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            command=None,
            status="SUCCESS",
            file_size=1024,
        )
        assert db.should_skip(
            source="D:/src/file.mp3",
            dest="D:/dst/file.flac",
            job_type="convert",
            dest_file_exists=True,
            dest_file_size=None,
        ) is True


class TestConversionDBDoesNotPrint:
    """``ConversionDB.__init__`` must NOT write to stdout.

    The constructor is invoked once per worker thread during conversion
    (and again from the prefilter). Any ``print`` or ``rprint`` call
    there races with the Rich Live progress display and corrupts the
    terminal — that was the source of the
    ``Schema already up-to-date (v2)`` spam underneath the bar.

    Migration messages are still available via
    ``migrate_to_current().messages`` for callers that want them
    (e.g. ``cli/db_cmd.py``).
    """

    def test_open_does_not_write_to_stdout(self, tmp_path: Path, capsys) -> None:
        from src.history.db import ConversionDB

        db_path = tmp_path / "history.db"
        ConversionDB(db_path)

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"ConversionDB wrote to stdout: {captured.out!r}"
        )
        assert captured.err == "", (
            f"ConversionDB wrote to stderr: {captured.err!r}"
        )

    def test_open_with_existing_db_does_not_write_to_stdout(
        self, tmp_path: Path, capsys
    ) -> None:
        """A second open of the same DB (worker thread case) must also be silent."""
        from src.history.db import ConversionDB

        db_path = tmp_path / "history.db"
        ConversionDB(db_path)  # first open — creates schema

        capsys.readouterr()  # clear output from the first open

        ConversionDB(db_path)  # second open — already up to date

        captured = capsys.readouterr()
        assert captured.out == "", (
            f"ConversionDB wrote to stdout on second open: {captured.out!r}"
        )