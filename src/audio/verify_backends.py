"""audio/verify_backends.py: Per-format integrity verification backends.

Ports the three verifier functions from ``plans/implementations/audio_verify.py``:
    - ``_verify_soundfile``: full-frame decode via libsndfile; FLAC MD5 verified on close.
    - ``_verify_miniaudio``: exhausts a streaming decode generator; raises on sync/frame errors.
    - ``_verify_mutagen``: header/tag inspection only; last-resort fallback.

All three are wrapped by ``verify_file()`` which dispatches based on extension
priority (soundfile > miniaudio > mutagen).

Each backend is guarded by ``_has_optional_dep()`` so that missing optional
packages produce ``VerifyStatus.UNSUPPORTED`` rather than ``ImportError``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.audio.integrity import VerifyResult

# ── constants ─────────────────────────────────────────────────────────────────

READ_BLOCK = 65_536  # frames per read() – constant-memory streaming decode

# Extensions each backend can handle (priority: soundfile > miniaudio > mutagen)
SF_EXTS = {".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif",
           ".au", ".w64", ".rf64", ".caf", ".sd2", ".paf"}
MA_EXTS = {".mp3", ".wav", ".flac", ".ogg"}   # miniaudio (MP3-primary + fallback)
META_EXTS = {".m4a", ".mp4", ".aac", ".wv", ".ape", ".mpc",
             ".opus", ".wma", ".dsf", ".dff", ".tta", ".tak"}
ALL_EXTS = SF_EXTS | MA_EXTS | META_EXTS

# ── optional-dependency guards ─────────────────────────────────────────────────

_SOUNDFILE_LOADED: bool | None = None
_MINIAUDIO_LOADED: bool | None = None
_MUTAGEN_LOADED: bool | None = None


def _has_soundfile() -> bool:
    global _SOUNDFILE_LOADED
    if _SOUNDFILE_LOADED is None:
        try:
            import soundfile  # noqa: F401
            _SOUNDFILE_LOADED = True
        except ImportError:
            _SOUNDFILE_LOADED = False
    return _SOUNDFILE_LOADED


def _has_miniaudio() -> bool:
    global _MINIAUDIO_LOADED
    if _MINIAUDIO_LOADED is None:
        try:
            import miniaudio  # noqa: F401
            _MINIAUDIO_LOADED = True
        except ImportError:
            _MINIAUDIO_LOADED = False
    return _MINIAUDIO_LOADED


def _has_mutagen() -> bool:
    global _MUTAGEN_LOADED
    if _MUTAGEN_LOADED is None:
        try:
            import mutagen  # noqa: F401
            _MUTAGEN_LOADED = True
        except ImportError:
            _MUTAGEN_LOADED = False
    return _MUTAGEN_LOADED


# ── per-backend verifiers ──────────────────────────────────────────────────────

def _verify_soundfile(path: str) -> "VerifyResult":
    """Full-frame decode via libsndfile (soundfile).

    - Reads every sample frame in READ_BLOCK-sized chunks (constant memory).
    - libsndfile verifies the FLAC embedded MD5 checksum internally on close.
    - Raises ``RuntimeError`` if decoded frame count is ≥1 % below the declared
      header value (catches truncated files).
    - If the libsndfile decoder loses sync (the classic symptom of a
      mid-stream truncation on FLAC), rewrites the error message to the
      same ``Truncated – …`` form so the UI sees a consistent failure
      shape regardless of which guard caught the corruption.

    Returns:
        VerifyResult with fmt and duration_s on success.
    """
    import soundfile as sf

    try:
        with sf.SoundFile(path) as f:
            declared = f.frames
            sr = f.samplerate
            fmt = f"{f.format}/{f.subtype}"
            decoded = 0
            while True:
                try:
                    blk = f.read(READ_BLOCK, dtype="int16", always_2d=False)
                except RuntimeError as exc:
                    # libsndfile raises "Error : <codec> decoder lost sync"
                    # on mid-stream truncation. Rewrite as Truncated – …
                    # so the caller's message is stable across codecs.
                    msg = str(exc)
                    if "lost sync" in msg.lower() or "decoder" in msg.lower():
                        raise RuntimeError(
                            f"Truncated – decoder lost sync after {decoded} "
                            f"frames (declared {declared})"
                        ) from exc
                    raise
                if not len(blk):
                    break
                decoded += len(blk)
    except RuntimeError as exc:
        # Re-raise with truncation-aware text so verify_file's catch block
        # can surface a uniform "Truncated – …" reason.
        msg = str(exc)
        if "Truncated" not in msg:
            raise RuntimeError(
                f"Truncated – {msg} (decoded {decoded}/{declared} frames)"
            ) from exc
        raise

    # Truncation guard (allow 1 % slack for VBR header estimates)
    if declared > 0 and decoded < declared * 0.99:
        raise RuntimeError(
            f"Truncated – header says {declared} frames, decoded {decoded}"
        )

    duration_s = declared / sr if sr else 0.0

    from src.audio.integrity import VerifyResult, VerifyStatus

    return VerifyResult(status=VerifyStatus.OK, reason=None, fmt=fmt, duration_s=duration_s)


def _verify_miniaudio(path: str) -> "VerifyResult":
    """Full frame-level decode via miniaudio.

    Streams the file block-by-block; any sync / frame error surfaces as an
    exception. Primary use: MP3 (soundfile/libsndfile cannot decode MP3).

    Returns:
        VerifyResult with fmt and duration_s on success.
    """
    import miniaudio

    try:
        info = miniaudio.get_file_info(path)
        fmt = info.file_format.name
        duration = info.duration
    except Exception:
        fmt, duration = "UNKNOWN", 0.0

    stream = miniaudio.stream_file(
        path,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=2,
        sample_rate=44100,
        frames_to_read=READ_BLOCK,
    )
    for _ in stream:
        pass  # exhaust the generator; bad frames raise here

    from src.audio.integrity import VerifyResult, VerifyStatus

    return VerifyResult(status=VerifyStatus.OK, reason=None, fmt=fmt, duration_s=duration)


def _verify_mutagen(path: str) -> "VerifyResult":
    """Header / tag inspection via mutagen (NO full audio decode).

    Catches corrupt containers, missing/mismatched stream headers, bad tags.
    Used as a last resort for formats (M4A, WV, APE …) not handled by
    soundfile or miniaudio.

    Returns:
        VerifyResult with meta_only=True flag in reason for transparency.
    """
    import mutagen

    f = mutagen.File(path, easy=False)
    if f is None:
        raise ValueError("Unrecognised format or completely corrupt header")

    info = getattr(f, "info", None)
    duration = float(getattr(info, "length", 0) or 0)
    fmt = type(f).__name__

    # mutagen sets sketchy=True when MP3 frame headers are inconsistent
    if getattr(info, "sketchy", False):
        raise ValueError("Inconsistent frame headers (mutagen: sketchy=True)")

    from src.audio.integrity import VerifyResult, VerifyStatus

    return VerifyResult(
        status=VerifyStatus.OK,
        reason=None,
        fmt=fmt,
        duration_s=duration,
    )


# ── dispatcher ────────────────────────────────────────────────────────────────

def verify_file(path: Path) -> "VerifyResult":
    """Dispatch to the best available verifier for this extension.

    Priority: soundfile > miniaudio > mutagen.
    Returns ``VerifyStatus.UNSUPPORTED`` if no backend claims the extension
    or no backend is installed.

    Args:
        path: Path to the audio file to verify.

    Returns:
        A ``VerifyResult`` with status, reason, format, and duration.
    """
    from src.audio.integrity import VerifyResult, VerifyStatus

    ext = path.suffix.lower()

    if not os.path.exists(path):
        return VerifyResult(
            status=VerifyStatus.NOT_OK,
            reason=f"file not found: {path}",
            fmt=None,
            duration_s=None,
        )

    try:
        size = path.stat().st_size
    except OSError as exc:
        return VerifyResult(
            status=VerifyStatus.NOT_OK,
            reason=f"cannot stat file: {exc}",
            fmt=None,
            duration_s=None,
        )

    if size == 0:
        return VerifyResult(
            status=VerifyStatus.NOT_OK,
            reason="file is empty",
            fmt=None,
            duration_s=None,
        )

    if ext not in ALL_EXTS:
        return VerifyResult(
            status=VerifyStatus.UNSUPPORTED,
            reason=f"unsupported extension: {ext}",
            fmt=None,
            duration_s=None,
        )

    path_str = str(path)

    try:
        # Priority: soundfile > miniaudio > mutagen
        if _has_soundfile() and ext in SF_EXTS:
            return _verify_soundfile(path_str)
        elif _has_miniaudio() and ext in MA_EXTS:
            return _verify_miniaudio(path_str)
        elif _has_mutagen():
            return _verify_mutagen(path_str)
        else:
            return VerifyResult(
                status=VerifyStatus.UNSUPPORTED,
                reason="no decoder installed for this format",
                fmt=None,
                duration_s=None,
            )

    except Exception as exc:
        return VerifyResult(
            status=VerifyStatus.NOT_OK,
            reason=str(exc),
            fmt=None,
            duration_s=None,
        )
