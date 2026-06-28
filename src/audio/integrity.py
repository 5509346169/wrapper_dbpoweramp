"""audio/integrity.py: Post-conversion integrity verification dispatcher.

Integrates the full-frame decode verifier (soundfile > miniaudio > mutagen)
into the run pipeline. The ``verify_file()`` function is the single
dispatch chokepoint; all backends are looked up through the
``src.audio.verify_backends`` shim so tests can monkey-patch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.audio.verify_backends import VerifyResult as _BackendResult


class VerifyStatus(str, Enum):
    """Result of a post-write integrity check."""

    OK = "OK"
    NOT_OK = "NOT_OK"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class VerifyResult:
    """Result of a post-write integrity check.

    Attributes:
        status:    The verification outcome.
        reason:    Human-readable reason (used for NOT_OK and UNSUPPORTED).
        fmt:       Codec/container string, e.g. "FLAC/PCM_24", "MP3".
        duration_s: Duration in seconds, if known.
    """

    status: VerifyStatus
    reason: str | None = None
    fmt: str | None = None
    duration_s: float | None = None

    @property
    def short(self) -> str:
        """Return the two-line user-facing form: ``Okay`` or ``Not - <reason>``."""
        if self.status is VerifyStatus.OK:
            return "Okay"
        if self.status is VerifyStatus.UNSUPPORTED:
            return f"Skipped - {self.reason or 'unsupported format'}"
        return f"Not - {self.reason or 'unknown reason'}"


def _import_verifiers():
    """Lazily import backends to allow optional-dependency mocking in tests."""
    from src.audio import verify_backends

    return verify_backends


def verify_file(path: Path) -> VerifyResult:
    """Dispatch to the best available backend for this file.

    Priority: soundfile > miniaudio > mutagen.
    Returns ``VerifyStatus.UNSUPPORTED`` if no backend claims the extension
    or no backend is installed.

    Args:
        path: Path to the audio file to verify.

    Returns:
        A ``VerifyResult`` with status, reason, format, and duration.
    """
    vb = _import_verifiers()
    return vb.verify_file(path)


def verify_file_with_result(path: Path) -> tuple[VerifyStatus, str | None, str | None, float | None]:
    """Convenience wrapper that returns a flat tuple for ``run_job.py``.

    Returns:
        (status, reason, fmt, duration_s)
    """
    result = verify_file(path)
    return result.status, result.reason, result.fmt, result.duration_s
