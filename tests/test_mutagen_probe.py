"""tests/test_mutagen_probe.py: Tests for mutagen-based Tier 3 lossy detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audio.inspector import (
    LOSSLESS_CODECS,
    _is_lossy_by_mutagen,
    is_lossy,
    probe_many,
)
from src.exceptions import ProbeError


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class MockAudioInfo:
    """Minimal mock mutagen audio.info object."""

    codec: str = ""
    codec_description: str = ""


class MockAudio:
    """Minimal mock mutagen File (MutagenFile) return value."""

    def __init__(self, codec: str = "", codec_description: str = "") -> None:
        self.info = MockAudioInfo(codec=codec, codec_description=codec_description)


def _make_mock_audio(codec: str = "", codec_description: str = "") -> MagicMock:
    """Create a properly-configured MagicMock that mimics a mutagen audio object."""
    mock = MagicMock()
    mock.info.codec = codec
    mock.info.codec_description = codec_description
    return mock


# ---------------------------------------------------------------------------
# _is_lossy_by_mutagen tests
# ---------------------------------------------------------------------------

class TestIsLossyByMutagen:
    """Tests for _is_lossy_by_mutagen."""

    def test_alac_m4a_is_not_lossy(self) -> None:
        """ALAC codec in an M4A returns False (lossless)."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="alac", codec_description="Apple Lossless"
            )
            result = _is_lossy_by_mutagen(Path("test.m4a"))
            assert result is False

    def test_aac_m4a_is_lossy(self) -> None:
        """AAC codec in an M4A returns True (lossy)."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="aac", codec_description="Advanced Audio Coding"
            )
            result = _is_lossy_by_mutagen(Path("test.m4a"))
            assert result is True

    def test_flac_is_not_lossy(self) -> None:
        """FLAC codec returns False (lossless)."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="flac", codec_description="FLAC (Free Lossless Audio Codec)"
            )
            result = _is_lossy_by_mutagen(Path("test.flac"))
            assert result is False

    def test_opus_is_lossy(self) -> None:
        """Opus codec returns True (lossy)."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="opus", codec_description="Opus"
            )
            result = _is_lossy_by_mutagen(Path("test.opus"))
            assert result is True

    def test_pcm_s16le_is_not_lossy(self) -> None:
        """PCM signed 16-bit little-endian is lossless."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="pcm_s16le", codec_description="PCM signed 16-bit little-endian"
            )
            result = _is_lossy_by_mutagen(Path("test.wav"))
            assert result is False

    def test_alac_fallback_from_description(self) -> None:
        """Codec name empty but codec_description contains 'alac' -> not lossy."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="", codec_description="Apple Lossless Audio Codec"
            )
            result = _is_lossy_by_mutagen(Path("test.m4a"))
            assert result is False

    def test_mutagen_returns_none_raises_probe_error(self) -> None:
        """MutagenFile returns None for unrecognized format -> ProbeError."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = None
            with pytest.raises(ProbeError) as exc_info:
                _is_lossy_by_mutagen(Path("test.unknown"))
            assert "unrecognized format" in exc_info.value.stderr

    def test_mutagen_read_failure_raises_probe_error(self) -> None:
        """MutagenFile raises an exception -> ProbeError."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.side_effect = OSError("permission denied")
            with pytest.raises(ProbeError) as exc_info:
                _is_lossy_by_mutagen(Path("test.m4a"))
            assert "permission denied" in exc_info.value.stderr

    def test_unknown_codec_raises_probe_error(self) -> None:
        """Codec name is unknown and description doesn't contain alac -> ProbeError."""
        with patch("src.audio.inspector.MutagenFile") as mock_mf:
            mock_mf.return_value = _make_mock_audio(
                codec="", codec_description="Some unknown format"
            )
            with pytest.raises(ProbeError) as exc_info:
                _is_lossy_by_mutagen(Path("test.bin"))
            assert "unknown codec" in exc_info.value.stderr


# ---------------------------------------------------------------------------
# is_lossy cascade tests (Tier 1 + 2 bypass Tier 3)
# ---------------------------------------------------------------------------

class TestIsLossyCascade:
    """Tests that Tier 1 and 2 correctly bypass mutagen for unambiguous files."""

    def test_flac_extension_skips_mutagen(self) -> None:
        """Unambiguous .flac extension -> mutagen is never called."""
        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            result = is_lossy(Path("test.flac"))
            assert result is False
            mock_tier3.assert_not_called()

    def test_mp3_extension_skips_mutagen(self) -> None:
        """Unambiguous .mp3 extension -> mutagen is never called."""
        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            result = is_lossy(Path("test.mp3"))
            assert result is True
            mock_tier3.assert_not_called()

    def test_lossy_folder_token_skips_mutagen(self, tmp_path: Path) -> None:
        """Lossy token in folder name -> mutagen is never called."""
        subfolder = tmp_path / "[320Kbps-AAC]"
        subfolder.mkdir()
        audio_file = subfolder / "track.m4a"
        audio_file.touch()
        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            result = is_lossy(audio_file)
            assert result is True
            mock_tier3.assert_not_called()

    def test_ambiguous_m4a_calls_mutagen(self) -> None:
        """Ambiguous .m4a without lossy folder token -> mutagen IS called."""
        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            mock_tier3.return_value = False
            result = is_lossy(Path("test.m4a"))
            assert result is False
            mock_tier3.assert_called_once_with(Path("test.m4a"))


# ---------------------------------------------------------------------------
# probe_many tests
# ---------------------------------------------------------------------------

class TestProbeMany:
    """Tests for probe_many with mocked mutagen."""

    def test_probe_many_lossless_and_lossy(self, tmp_path: Path) -> None:
        """probe_many returns correct True/False for mixed codec files."""
        # Create files - .flac is unambiguous, .m4a needs mutagen
        flac_file = tmp_path / "album" / "track.flac"
        flac_file.parent.mkdir()
        flac_file.touch()

        m4a_file = tmp_path / "album" / "track.m4a"
        m4a_file.touch()

        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            mock_tier3.side_effect = lambda f: f.suffix.lower() != ".flac"
            result = probe_many([flac_file, m4a_file], workers=2)

        assert result[flac_file] is False
        assert result[m4a_file] is True

    def test_probe_many_no_ambiguous_files(self, tmp_path: Path) -> None:
        """probe_many with only unambiguous files -> no mutagen calls."""
        mp3_file = tmp_path / "track.mp3"
        mp3_file.touch()
        flac_file = tmp_path / "track.flac"
        flac_file.touch()

        with patch("src.audio.inspector._is_lossy_by_mutagen") as mock_tier3:
            result = probe_many([mp3_file, flac_file], workers=2)
            assert result[mp3_file] is True
            assert result[flac_file] is False
            mock_tier3.assert_not_called()
