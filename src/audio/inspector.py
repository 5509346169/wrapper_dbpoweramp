"""audio/inspector.py: Multi-tier lossy detection.

Detection cascade (fastest first):
  1. Extension — deterministic, zero I/O.
  2. Folder-name heuristic — zero I/O (e.g. "[256Kbps-AAC]" in the path).
  3. ffprobe stream probe — only for files where tiers 1-2 are inconclusive
     (currently only .m4a, which can host ALAC or AAC inside the same container).

For callers that need futures (streaming progress), a dedicated
``probe_generator`` fires ffprobe only for the ambiguous subset, while
extension and folder-name checks run synchronously on the main thread.
"""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from src.exceptions import ProbeError


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1: Extension lookup
# ─────────────────────────────────────────────────────────────────────────────

# Lossless codecs (self-contained container+codec — unambiguously lossless
# regardless of internal content, since the container IS the codec).
UNAMBIGUOUS_LOSSLESS_EXT: frozenset[str] = frozenset({
    ".flac", ".fla", ".ape", ".wv", ".tta", ".tak",
    ".ofr", ".ofs", ".shn",           # optimFROG, shorten
    # uncompressed PCM containers (container IS lossless PCM)
    ".wav", ".aiff", ".aif", ".caf", ".bwf", ".au", ".pcm", ".raw",
})

# Ambiguous extensions — the container can hold either lossless or lossy codecs.
# These require Tier 3 (ffprobe) to resolve.
AMBIGUOUS_EXT: frozenset[str] = frozenset({
    ".m4a", ".mp4", ".caf",           # ALAC vs AAC
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
    requires Tier 3 (ffprobe) to resolve.
    """
    ext = path.suffix.lower()
    if ext in UNAMBIGUOUS_LOSSLESS_EXT:
        return False
    if ext in UNAMBIGUOUS_LOSSY_EXT:
        return True
    return None  # ambiguous — needs stream probe


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2: Folder-name heuristic
# ─────────────────────────────────────────────────────────────────────────────

# Folder-name tokens that signal a lossy source.  These patterns appear in
# download/release directory names and let us skip the expensive ffprobe call
# for tagged releases.
LOSSY_FOLDER_TOKENS: frozenset[str] = frozenset({
    # bitrate + codec variants
    "aac", "mp3", "v0", "v2",
    "128k", "192k", "256k", "320k",
    "128kbps", "192kbps", "256kbps", "320kbps",
    "lame", "l3tag",
    # lossy codec names
    "ogg", "vorbis", "opus", "flac24",
    # streaming / low-quality markers
    "webrip", "shoprip", "itunes", "amazon",
    "deezer", "spotify", "tidal", "qobuz",
    # general lossy umbrella (catch-all last)
    "mp3", "lossy",
})


def _is_lossy_by_folder(path: Path) -> Optional[bool]:
    """Tier 2: return True/False if a lossy token is found in any parent dir, else None.

    Scans from the file's immediate parent up to the filesystem root.
    Stops at the first directory whose name is entirely numeric (e.g. a numeric
    folder like "26005" in a sequential scan) to avoid false positives.
    """
    current: Optional[Path] = path.parent
    while current is not None:
        folder_lower = current.name.lower()
        # Stop scanning upward at purely numeric directory names (common in
        # sorted/concatenated rips and some tool outputs).
        if folder_lower.isdigit():
            break
        for token in LOSSY_FOLDER_TOKENS:
            if token in folder_lower:
                return True
        current = current.parent
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3: ffprobe stream probe
# ─────────────────────────────────────────────────────────────────────────────

LOSSLESS_CODECS: frozenset[str] = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "shorten", "als",           # MPEG-4 ALS
    "g711", "g711a", "g711u",   # PCM-alike telco codecs
}


def probe_codec(file: Path, ffprobe_binary: str) -> str:
    """Returns ffprobe's codec_name for the first audio stream. Raises ProbeError on failure."""
    import subprocess

    args = [
        ffprobe_binary,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    stdout = result.stdout.strip()
    if result.returncode != 0 or not stdout:
        raise ProbeError(str(file), result.stderr.strip() or "no output")
    return stdout


def _is_lossy_by_probe(file: Path, ffprobe_binary: str) -> bool:
    """Tier 3: run ffprobe and return True if the codec is not in LOSSLESS_CODECS."""
    codec = probe_codec(file, ffprobe_binary)
    return codec not in LOSSLESS_CODECS


# ─────────────────────────────────────────────────────────────────────────────
# Combined cascade
# ─────────────────────────────────────────────────────────────────────────────

def is_lossy(file: Path, ffprobe_binary: str) -> bool:
    """Three-tier lossy detection for a single file.

    Tiers (in order):
      1. Extension — unambiguous extensions resolved immediately.
      2. Folder-name heuristic — lossy token in any parent directory.
      3. ffprobe stream probe — only for ambiguous extensions (.m4a, etc.).

    Returns True if the file is lossy, False if confirmed lossless.
    Raises ProbeError only when ffprobe is invoked and fails.
    """
    # Tier 1
    ext_result = _is_lossy_by_ext(file)
    if ext_result is not None:
        return ext_result

    # Tier 2
    folder_result = _is_lossy_by_folder(file)
    if folder_result is not None:
        return folder_result

    # Tier 3 — the only path that hits the filesystem
    return _is_lossy_by_probe(file, ffprobe_binary)


# ─────────────────────────────────────────────────────────────────────────────
# Batch utilities (parallel futures for the Tier-3 subset)
# ─────────────────────────────────────────────────────────────────────────────

def _classify_by_ext_and_folder(files: list[Path]) -> dict[Path, Optional[bool]]:
    """Apply tiers 1 and 2 to every file in one synchronous pass.

    Returns a dict mapping each file to True/False (tiers 1-2 resolved)
    or None (needs Tier 3 probe).
    """
    result: dict[Path, Optional[bool]] = {}
    for f in files:
        ext_result = _is_lossy_by_ext(f)
        if ext_result is not None:
            result[f] = ext_result
            continue
        folder_result = _is_lossy_by_folder(f)
        if folder_result is not None:
            result[f] = folder_result
            continue
        result[f] = None  # needs Tier 3
    return result


def probe_generator(
    files: list[Path], ffprobe_binary: str, workers: int
) -> tuple[Future, ...]:
    """Launch ffprobe only for the Tier-3 ambiguous subset.

    Extension and folder-name checks are applied synchronously in the calling
    thread before the executor is even created, so no worker time is wasted
    on unambiguous files.
    """
    classified = _classify_by_ext_and_folder(files)
    ambiguous_files = [f for f, v in classified.items() if v is None]

    if not ambiguous_files:
        # Nothing needs ffprobe — return futures that immediately yield (None, False).
        # We return empty tuple and the caller handles it; the caller checks
        # classified dict for any-None entries before calling this.
        return ()

    def probe_one(file: Path) -> tuple[Path, bool]:
        return (file, _is_lossy_by_probe(file, ffprobe_binary))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(probe_one, f) for f in ambiguous_files]
    return tuple(futures)


def probe_many(
    files: list[Path], ffprobe_binary: str, workers: int
) -> dict[Path, bool]:
    """Three-tier lossy detection for a batch of files (blocking convenience wrapper).

    Extension and folder-name are applied synchronously first; ffprobe is fired
    only for the ambiguous subset (.m4a, etc.) in a thread pool.
    """
    classified = _classify_by_ext_and_folder(files)
    ambiguous_files = [f for f, v in classified.items() if v is None]

    # Resolve ambiguous files in parallel
    ambiguous_results: dict[Path, bool] = {}
    if ambiguous_files:
        for future in as_completed(probe_generator(ambiguous_files, ffprobe_binary, workers)):
            f, result = future.result()
            ambiguous_results[f] = result

    # Merge results
    final: dict[Path, bool] = {}
    for f, v in classified.items():
        if v is not None:
            final[f] = v
        else:
            final[f] = ambiguous_results[f]
    return final
