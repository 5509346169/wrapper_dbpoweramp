"""jobs/builder.py: Build ConversionJob lists from discovered audio files."""

from pathlib import Path

from audio.inspector import probe_many
from models.types import ConversionJob, LossyAction, PresetConfig
from pathing.resolver import compute_output_path


AUDIO_EXTENSIONS: set[str] = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".ape", ".wv", ".tta"}


def discover_audio_files(input_path: Path, excludes: list[str]) -> list[Path]:
    """
    Discover audio files from the given input path.

    Args:
        input_path: A file or directory to scan for audio files.
        excludes: List of directory names to exclude from the walk (basename match).

    Returns:
        List of Path objects for discovered audio files.
    """
    if input_path.is_file():
        return [input_path]

    exclude_set = set(excludes)
    audio_files: list[Path] = []

    for item in input_path.rglob("*"):
        if item.is_dir():
            continue
        if item.suffix.lower() in AUDIO_EXTENSIONS:
            if item.parent.name not in exclude_set:
                audio_files.append(item)

    return sorted(audio_files)


def build_jobs(
    files: list[Path],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    ffprobe_binary: str,
    probe_workers: int,
) -> tuple[list[ConversionJob], list[Path]]:
    """
    Build ConversionJob list from discovered audio files.

    Args:
        files: List of audio file paths to build jobs for.
        input_root: The root of the input path.
        source_root: If given, used as base for relative path computation.
        output_root: The root directory for output files.
        preset: The preset configuration to use.
        lossy_action: What to do with lossy source files (None = leave unspecified).
        no_lossy_check: If True, skip lossy probing entirely.
        ffprobe_binary: Path to the ffprobe binary.
        probe_workers: Number of workers for parallel probing.

    Returns:
        A tuple of (jobs, lossy_files_found) where:
        - jobs: List of ConversionJob objects for execution (skip jobs excluded from execution).
        - lossy_files_found: List of lossy file paths (for caller to abort if needed).
    """
    lossy_files_found: list[Path] = []

    if no_lossy_check:
        is_lossy_map: dict[Path, bool | None] = {f: None for f in files}
    else:
        is_lossy_map = probe_many(files, ffprobe_binary, probe_workers)
        lossy_files_found = [f for f, lossy in is_lossy_map.items() if lossy]

    jobs: list[ConversionJob] = []
    for f in files:
        is_lossy = is_lossy_map.get(f)

        if no_lossy_check:
            job_type: str = "convert"
            reason = None
        elif is_lossy:
            if lossy_action is None:
                job_type = "skip"
                reason = "lossy source, action=abort"
            elif lossy_action == LossyAction.LEAVE:
                job_type = "skip"
                reason = "lossy source, action=leave"
            elif lossy_action == LossyAction.COPY:
                job_type = "copy"
                reason = "lossy source, action=copy"
            elif lossy_action == LossyAction.CONVERT:
                job_type = "convert"
                reason = "lossy source, action=convert"
        else:
            job_type = "convert"
            reason = None

        outfile = compute_output_path(
            f,
            input_root,
            source_root,
            output_root,
            preset.ext,
        )

        job = ConversionJob(
            infile=f,
            outfile=outfile,
            preset=preset,
            job_type=job_type,
            is_lossy_source=is_lossy,
            reason=reason,
        )
        jobs.append(job)

    return (jobs, lossy_files_found)
