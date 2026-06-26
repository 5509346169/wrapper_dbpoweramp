"""audio/inspector.py: Backward-compatibility shim.

The implementation has been split into:

* :mod:`src.audio.extensions`      — Tier 1: file-extension lookup
* :mod:`src.audio.folder_heuristic` — Tier 2: folder-name heuristic
* :mod:`src.audio.mutagen_probe`  — Tier 3: mutagen metadata probe
* :mod:`src.audio.cascade`        — three-tier single-file cascade
* :mod:`src.audio.batch`          — batch and parallel-future utilities

This module re-exports the same public/private names from those locations
so existing imports (e.g. ``from src.audio.inspector import is_lossy``)
continue to work. ``MutagenFile`` is re-exported because tests monkey-patch
it here as well.
"""

from mutagen import File as MutagenFile

from src.audio.batch import _classify_by_ext_and_folder, probe_generator, probe_many
from src.audio.cascade import is_lossy
from src.audio.extensions import (
    ALL_LOSSY_EXT,
    AMBIGUOUS_EXT,
    UNAMBIGUOUS_LOSSLESS_EXT,
    UNAMBIGUOUS_LOSSY_EXT,
    _is_lossy_by_ext,
)
from src.audio.folder_heuristic import LOSSY_FOLDER_TOKENS, _is_lossy_by_folder
from src.audio.mutagen_probe import LOSSLESS_CODECS, _is_lossy_by_mutagen

__all__ = [
    "ALL_LOSSY_EXT",
    "AMBIGUOUS_EXT",
    "LOSSLESS_CODECS",
    "LOSSY_FOLDER_TOKENS",
    "MutagenFile",
    "UNAMBIGUOUS_LOSSLESS_EXT",
    "UNAMBIGUOUS_LOSSY_EXT",
    "_classify_by_ext_and_folder",
    "_is_lossy_by_ext",
    "_is_lossy_by_folder",
    "_is_lossy_by_mutagen",
    "is_lossy",
    "probe_generator",
    "probe_many",
]
