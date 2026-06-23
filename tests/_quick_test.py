"""Quick inline test runner to verify mutagen tests pass."""
import sys
from pathlib import Path

# Run individual tests without pytest to avoid hang
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audio.inspector import (
    _is_lossy_by_mutagen,
    is_lossy,
    probe_many,
)
from src.exceptions import ProbeError


def make_mock_audio(codec="", codec_description=""):
    m = MagicMock()
    m.info.codec = codec
    m.info.codec_description = codec_description
    return m


# Test 1: ALAC
with patch("src.audio.inspector.MutagenFile") as mock:
    mock.return_value = make_mock_audio("alac", "Apple Lossless")
    r = _is_lossy_by_mutagen(Path("test.m4a"))
    assert r is False, f"ALAC should be lossless, got {r}"
    print("PASS: ALAC is lossless")


# Test 2: AAC
with patch("src.audio.inspector.MutagenFile") as mock:
    mock.return_value = make_mock_audio("aac", "Advanced Audio Coding")
    r = _is_lossy_by_mutagen(Path("test.m4a"))
    assert r is True, f"AAC should be lossy, got {r}"
    print("PASS: AAC is lossy")


# Test 3: ALAC fallback from description
with patch("src.audio.inspector.MutagenFile") as mock:
    mock.return_value = make_mock_audio("", "Apple Lossless Audio Codec")
    r = _is_lossy_by_mutagen(Path("test.m4a"))
    assert r is False, f"ALAC fallback should be lossless, got {r}"
    print("PASS: ALAC fallback from description is lossless")


# Test 4: MutagenFile returns None
with patch("src.audio.inspector.MutagenFile") as mock:
    mock.return_value = None
    try:
        _is_lossy_by_mutagen(Path("test.bin"))
        assert False, "Should have raised ProbeError"
    except ProbeError as e:
        assert "unrecognized format" in e.stderr
    print("PASS: None return raises ProbeError")


# Test 5: MutagenFile raises
with patch("src.audio.inspector.MutagenFile") as mock:
    mock.side_effect = OSError("permission denied")
    try:
        _is_lossy_by_mutagen(Path("test.m4a"))
        assert False, "Should have raised ProbeError"
    except ProbeError as e:
        assert "permission denied" in e.stderr
    print("PASS: OSError raises ProbeError")


# Test 6: FLAC extension skips mutagen
with patch("src.audio.inspector._is_lossy_by_mutagen") as mock:
    r = is_lossy(Path("test.flac"))
    assert r is False
    mock.assert_not_called()
    print("PASS: FLAC extension skips mutagen")


# Test 7: MP3 extension skips mutagen
with patch("src.audio.inspector._is_lossy_by_mutagen") as mock:
    r = is_lossy(Path("test.mp3"))
    assert r is True
    mock.assert_not_called()
    print("PASS: MP3 extension skips mutagen")


# Test 8: Ambiguous M4A calls mutagen
with patch("src.audio.inspector._is_lossy_by_mutagen") as mock:
    mock.return_value = False
    r = is_lossy(Path("test.m4a"))
    assert r is False
    mock.assert_called_once_with(Path("test.m4a"))
    print("PASS: M4A calls mutagen")


# Test 9: probe_many with unambiguous files only
with patch("src.audio.inspector._is_lossy_by_mutagen") as mock:
    mp3 = Path("test.mp3")
    flac = Path("test.flac")
    r = probe_many([mp3, flac], workers=2)
    assert r[mp3] is True
    assert r[flac] is False
    mock.assert_not_called()
    print("PASS: probe_many with unambiguous files skips mutagen")


# Test 10: probe_many with mixed files
with patch("src.audio.inspector._is_lossy_by_mutagen") as mock:
    def side(f):
        return f.suffix.lower() != ".flac"
    mock.side_effect = side
    flac = Path("album/track.flac")
    m4a = Path("album/track.m4a")
    r = probe_many([flac, m4a], workers=2)
    assert r[flac] is False
    assert r[m4a] is True
    print("PASS: probe_many with mixed files")


print("\nAll 10 tests passed!")
