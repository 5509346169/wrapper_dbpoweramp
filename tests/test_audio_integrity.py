"""tests/test_audio_integrity.py: Unit tests for the audio integrity verifier."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _closed_temp_file(suffix: str, content: bytes = b"") -> Path:
    """Create a temp file, close its handle, return the Path."""
    fd, name = tempfile.mkstemp(suffix=suffix)
    if content:
        os.write(fd, content)
    os.close(fd)
    return Path(name)

# Determine what's available
try:
    import soundfile  # noqa: F401
    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False

try:
    import miniaudio  # noqa: F401
    HAS_MINIAUDIO = True
except ImportError:
    HAS_MINIAUDIO = False

try:
    import mutagen  # noqa: F401
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

# Skip all tests if no audio libraries are available
NO_AUDIO_LIBS = not (HAS_SOUNDFILE or HAS_MINIAUDIO or HAS_MUTAGEN)


class TestVerifyStatus:
    """Tests for VerifyStatus enum."""

    def test_verify_status_values(self):
        from src.audio.integrity import VerifyStatus

        assert VerifyStatus.OK.value == "OK"
        assert VerifyStatus.NOT_OK.value == "NOT_OK"
        assert VerifyStatus.UNSUPPORTED.value == "UNSUPPORTED"


class TestVerifyResult:
    """Tests for VerifyResult dataclass."""

    def test_short_ok(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.OK)
        assert r.short == "Okay"

    def test_short_not_ok(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.NOT_OK, reason="Truncated – header says 1234 frames")
        assert r.short == "Not - Truncated – header says 1234 frames"

    def test_short_unsupported(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.UNSUPPORTED, reason="unsupported format: .xyz")
        assert r.short == "Skipped - unsupported format: .xyz"

    def test_short_unsupported_no_reason(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.UNSUPPORTED)
        assert r.short == "Skipped - unsupported format"

    def test_short_not_ok_no_reason(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(status=VerifyStatus.NOT_OK)
        assert r.short == "Not - unknown reason"

    def test_fields(self):
        from src.audio.integrity import VerifyResult, VerifyStatus

        r = VerifyResult(
            status=VerifyStatus.OK,
            reason=None,
            fmt="FLAC/PCM_16",
            duration_s=123.456,
        )
        assert r.status is VerifyStatus.OK
        assert r.reason is None
        assert r.fmt == "FLAC/PCM_16"
        assert r.duration_s == 123.456


class TestVerifyFileDispatch:
    """Tests for the verify_file() dispatcher."""

    def test_nonexistent_file(self):
        from src.audio.integrity import VerifyResult, VerifyStatus, verify_file

        result = verify_file(Path("/nonexistent/file.flac"))
        assert result.status is VerifyStatus.NOT_OK
        assert "not found" in result.reason

    def test_unsupported_extension(self):
        from src.audio.integrity import VerifyStatus, verify_file

        path = _closed_temp_file(".xyz", b"not an audio file")
        try:
            result = verify_file(path)
            assert result.status is VerifyStatus.UNSUPPORTED
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file(self):
        from src.audio.integrity import VerifyStatus, verify_file

        path = _closed_temp_file(".flac", b"")
        try:
            result = verify_file(path)
            assert result.status is VerifyStatus.NOT_OK
            assert "empty" in result.reason
        finally:
            path.unlink(missing_ok=True)


@pytest.mark.skipif(NO_AUDIO_LIBS, reason="No audio libraries available")
class TestVerifyBackendsSoundfile:
    """Tests for the soundfile backend (FLAC)."""

    def test_flac_ok(self, tmp_path: Path):
        import numpy as np

        if not HAS_SOUNDFILE:
            pytest.skip("soundfile not available")

        import soundfile as sf

        # Create a valid FLAC file
        flac_path = tmp_path / "test.flac"
        data = (np.random.uniform(-1, 1, 44100 * 2)).astype(np.float32)  # 2 seconds of audio
        sf.write(str(flac_path), data, 44100, format="FLAC", subtype="PCM_16")

        from src.audio.integrity import VerifyStatus, verify_file

        result = verify_file(flac_path)
        assert result.status is VerifyStatus.OK
        assert result.fmt is not None
        assert "FLAC" in result.fmt
        assert result.duration_s is not None
        assert result.duration_s > 0

    def test_flac_truncated(self, tmp_path: Path):
        import numpy as np

        if not HAS_SOUNDFILE:
            pytest.skip("soundfile not available")

        import soundfile as sf

        # Create a valid FLAC file then truncate it
        flac_path = tmp_path / "truncated.flac"
        data = (np.random.uniform(-1, 1, 44100 * 10)).astype(np.float32)  # 10 seconds
        sf.write(str(flac_path), data, 44100, format="FLAC", subtype="PCM_16")

        # Truncate to 10% of the file
        size = flac_path.stat().st_size
        flac_path.write_bytes(flac_path.read_bytes()[: size // 10])

        from src.audio.integrity import VerifyStatus, verify_file

        result = verify_file(flac_path)
        assert result.status is VerifyStatus.NOT_OK
        assert "Truncated" in result.reason


class TestVerifyBackendsMutagen:
    """Tests for the mutagen backend."""

    def test_mutagen_unsupported_extension(self):
        if not HAS_MUTAGEN:
            pytest.skip("mutagen not available")

        from src.audio.integrity import VerifyStatus, verify_file

        path = _closed_temp_file(".xyz", b"not audio")
        try:
            result = verify_file(path)
            assert result.status is VerifyStatus.UNSUPPORTED
        finally:
            path.unlink(missing_ok=True)
