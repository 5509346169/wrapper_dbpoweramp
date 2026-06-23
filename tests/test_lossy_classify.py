"""tests/test_lossy_classify.py: Tests for _classify and enrich_index_rows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from src.jobs.builder import _classify, enrich_index_rows
from src.models.types import LossyAction, PresetConfig


@dataclass
class MockIndexRow:
    """Minimal IndexRow stand-in for testing _classify."""

    source_path: str
    dest_path: str
    job_type: str
    file_size: int
    sidecar_files: str
    mtime: float
    is_lossy: bool | None = None


class MockPreset:
    """Minimal PresetConfig for testing."""

    def __init__(self) -> None:
        self.ext = ".flac"


# ---------------------------------------------------------------------------
# _classify tests
# ---------------------------------------------------------------------------


class TestClassify:
    """Tests for _classify covering all LossyAction values and no_lossy_check."""

    def _make_row(self) -> MockIndexRow:
        return MockIndexRow(
            source_path="D:/music/test.mp3",
            dest_path="",
            job_type="",
            file_size=1000,
            sidecar_files="",
            mtime=0.0,
        )

    @patch("src.jobs.builder.compute_output_path")
    def test_no_lossy_check_sets_job_type_convert(self, mock_compute: object) -> None:
        """no_lossy_check=True always sets job_type to 'convert'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=None,
            lossy_action=None,
            no_lossy_check=True,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "convert"

    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_val_true_no_action_sets_skip(self, mock_compute: object) -> None:
        """is_lossy=True with lossy_action=None sets job_type to 'skip'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=True,
            lossy_action=None,
            no_lossy_check=False,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "skip"

    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_val_true_action_leave_sets_skip(self, mock_compute: object) -> None:
        """is_lossy=True with LossyAction.LEAVE sets job_type to 'skip'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=True,
            lossy_action=LossyAction.LEAVE,
            no_lossy_check=False,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "skip"

    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_val_true_action_copy_sets_copy(self, mock_compute: object) -> None:
        """is_lossy=True with LossyAction.COPY sets job_type to 'copy'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=True,
            lossy_action=LossyAction.COPY,
            no_lossy_check=False,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "copy"

    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_val_true_action_convert_sets_convert(self, mock_compute: object) -> None:
        """is_lossy=True with LossyAction.CONVERT sets job_type to 'convert'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=True,
            lossy_action=LossyAction.CONVERT,
            no_lossy_check=False,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "convert"

    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_val_false_sets_convert(self, mock_compute: object) -> None:
        """is_lossy=False sets job_type to 'convert'."""
        row = self._make_row()
        _classify(
            row=row,
            is_lossy_val=False,
            lossy_action=LossyAction.LEAVE,
            no_lossy_check=False,
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
        )
        assert row.job_type == "convert"


# ---------------------------------------------------------------------------
# enrich_index_rows tests
# ---------------------------------------------------------------------------


class TestEnrichIndexRows:
    """Blocking tests for enrich_index_rows."""

    @patch("src.jobs.builder.probe_many")
    @patch("src.jobs.builder.compute_output_path")
    def test_no_lossy_check_skips_probe(
        self, mock_compute: object, mock_probe_many: object
    ) -> None:
        """no_lossy_check=True skips probe_many entirely."""
        mock_compute.return_value = Path("D:/output/test.mp3")
        row = MockIndexRow(
            source_path="D:/music/test.mp3",
            dest_path="",
            job_type="",
            file_size=1000,
            sidecar_files="",
            mtime=0.0,
        )
        result = enrich_index_rows(
            rows=[row],
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
            lossy_action=LossyAction.LEAVE,
            no_lossy_check=True,
            ffprobe_path="ffprobe",
            probe_workers=2,
        )
        mock_probe_many.assert_not_called()
        assert result == []

    @patch("src.jobs.builder.probe_many")
    @patch("src.jobs.builder.compute_output_path")
    def test_lossy_file_returned_in_result(
        self, mock_compute: object, mock_probe_many: object
    ) -> None:
        """Files detected as lossy are returned in the lossy_files_found list."""
        mock_compute.return_value = Path("D:/output/test.mp3")
        row = MockIndexRow(
            source_path="D:/music/test.mp3",
            dest_path="",
            job_type="",
            file_size=1000,
            sidecar_files="",
            mtime=0.0,
        )
        mock_probe_many.return_value = {Path("D:/music/test.mp3"): True}
        result = enrich_index_rows(
            rows=[row],
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
            lossy_action=LossyAction.LEAVE,
            no_lossy_check=False,
            ffprobe_path="ffprobe",
            probe_workers=2,
        )
        assert result == [Path("D:/music/test.mp3")]
        assert row.job_type == "skip"

    @patch("src.jobs.builder.probe_many")
    @patch("src.jobs.builder.compute_output_path")
    def test_lossless_file_job_type_convert(
        self, mock_compute: object, mock_probe_many: object
    ) -> None:
        """Lossless files are always job_type 'convert'."""
        mock_compute.return_value = Path("D:/output/test.flac")
        row = MockIndexRow(
            source_path="D:/music/test.flac",
            dest_path="",
            job_type="",
            file_size=1000,
            sidecar_files="",
            mtime=0.0,
        )
        mock_probe_many.return_value = {Path("D:/music/test.flac"): False}
        result = enrich_index_rows(
            rows=[row],
            input_root=Path("D:/music"),
            source_root=None,
            output_root=Path("D:/output"),
            preset=MockPreset(),  # type: ignore[arg-type]
            lossy_action=LossyAction.LEAVE,
            no_lossy_check=False,
            ffprobe_path="ffprobe",
            probe_workers=2,
        )
        assert result == []
        assert row.job_type == "convert"
