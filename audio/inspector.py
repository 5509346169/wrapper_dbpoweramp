"""audio/inspector.py: Audio codec probing via ffprobe."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from exceptions import ProbeError


LOSSLESS_CODECS = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "shorten",
}


def probe_codec(file: Path, ffprobe_binary: str) -> str:
    """Returns ffprobe's codec_name for the first audio stream. Raises ProbeError on failure."""
    args = [
        ffprobe_binary,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file),
    ]
    import subprocess
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    stdout = result.stdout.strip()
    if result.returncode != 0 or not stdout:
        raise ProbeError(str(file), result.stderr.strip() or "no output")
    return stdout


def is_lossy(file: Path, ffprobe_binary: str) -> bool:
    """True if codec_name not in LOSSLESS_CODECS. Never infers from file extension."""
    codec = probe_codec(file, ffprobe_binary)
    return codec not in LOSSLESS_CODECS


def probe_many(files: list[Path], ffprobe_binary: str, workers: int) -> dict[Path, bool]:
    """Thread-pooled batch probe (I/O bound) — used for the pre-flight lossy-gate scan."""
    cache: dict[Path, bool] = {}

    def probe_one(file: Path) -> tuple[Path, bool]:
        if file in cache:
            return (file, cache[file])
        result = is_lossy(file, ffprobe_binary)
        cache[file] = result
        return (file, result)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(probe_one, files))

    return dict(results)
