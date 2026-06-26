"""audio/mutagen_probe.py: Tier 3 — mutagen metadata probe for lossy detection.

Reads the audio file with mutagen and inspects the codec name. This is the
only tier that actually opens the file, so it's reserved for ambiguous
extensions (.m4a, .mp4, .caf).

``MutagenFile`` is looked up through the :mod:`src.audio.inspector` shim at
call time so that existing tests (which monkey-patch
``src.audio.inspector.MutagenFile``) keep working without modification.
"""

import sys
from pathlib import Path

from src.exceptions import ProbeError


LOSSLESS_CODECS: frozenset[str] = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "shorten", "als",           # MPEG-4 ALS
    "g711", "g711a", "g711u",   # PCM-alike telco codecs
}


def _resolve_mutagen_file():
    """Return the current ``MutagenFile`` binding from ``src.audio.inspector``.

    Falls back to the real ``mutagen.File`` if the shim hasn't been imported
    yet. This indirection lets tests ``patch('src.audio.inspector.MutagenFile')``
    without needing to know about the new module layout.
    """
    import src.audio.inspector as _inspector_shim

    return getattr(_inspector_shim, "MutagenFile", None) or __import__(
        "mutagen", fromlist=["File"]
    ).File


def _is_lossy_by_mutagen(file: Path) -> bool:
    """Tier 3: read audio metadata with mutagen and return True if the codec is not lossless.

    Uses mutagen (pure Python, no subprocess).

    Raises ProbeError when mutagen cannot read the file or the format is
    unrecognized.
    """
    MutagenFile = _resolve_mutagen_file()
    try:
        audio = MutagenFile(file)
    except Exception as e:
        raise ProbeError(str(file), str(e))

    if audio is None:
        raise ProbeError(str(file), "unrecognized format")

    # For MP4/M4A: mutagen.mp4.MP4 stores codec in info.codec (e.g. "alac", "aac").
    # For other formats the codec name may come from the same attribute.
    codec_name = getattr(audio.info, "codec", "") or ""
    codec_name_lower = codec_name.lower()

    if codec_name_lower in LOSSLESS_CODECS:
        return False
    if codec_name_lower in {"", "unknown"}:
        # Fallback: try codec_description for formats that expose name there.
        desc = getattr(audio.info, "codec_description", "") or ""
        desc_lower = desc.lower()
        if "alac" in desc_lower or "apple lossless" in desc_lower:
            return False
        raise ProbeError(str(file), f"unknown codec: {codec_name!r} ({desc!r})")
    return True
