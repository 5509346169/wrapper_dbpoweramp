"""audio/extensions.py: Tier 1 — file-extension lookup for lossless/lossy classification.

The fastest tier: zero I/O, deterministic from the file's suffix.
"""

from pathlib import Path
from typing import Optional


# Lossless codecs (self-contained container+codec — unambiguously lossless
# regardless of internal content, since the container IS the codec).
UNAMBIGUOUS_LOSSLESS_EXT: frozenset[str] = frozenset({
    ".flac", ".fla", ".ape", ".wv", ".tta", ".tak",
    ".ofr", ".ofs", ".shn",           # optimFROG, shorten
    # uncompressed PCM containers (container IS lossless PCM)
    ".wav", ".aiff", ".aif", ".caf", ".bwf", ".au", ".pcm", ".raw",
})

# Ambiguous extensions — the container can hold either lossless or lossy codecs.
# These require Tier 3 (mutagen) to resolve.
AMBIGUOUS_EXT: frozenset[str] = frozenset({
    ".m4a", ".caf",           # ALAC vs AAC
})

# Extensions that are unambiguously lossy (deterministic, zero I/O needed).
UNAMBIGUOUS_LOSSY_EXT: frozenset[str] = frozenset({
    ".mp3", ".mp2", ".mp1",
    ".ogg", ".opus", ".spx",
    ".wma", ".wmv", ".asf",
    ".ac3", ".eac3",
    ".dts", ".dtshd", ".dtsma",
    ".amr", ".amrnb", ".amrwb",
    ".ra", ".rm", ".rmvb",
    ".aac", ".adts", ".loas",
    ".3gp", ".3g2",
    ".webm",
    ".ape",                                 # .ape is in unambiguous lossless above, but
                                            # also listed here for explicitness; it IS lossless.
})

ALL_LOSSY_EXT: frozenset[str] = (
    UNAMBIGUOUS_LOSSY_EXT | AMBIGUOUS_EXT
)


def _is_lossy_by_ext(path: Path) -> Optional[bool]:
    """Tier 1: return True/False if extension is unambiguous, else None.

    Returns None when the extension is ambiguous (.m4a, .mp4, .caf) and
    requires Tier 3 (mutagen) to resolve.
    """
    ext = path.suffix.lower()
    if ext in UNAMBIGUOUS_LOSSLESS_EXT:
        return False
    if ext in UNAMBIGUOUS_LOSSY_EXT:
        return True
    return None  # ambiguous — needs stream probe
