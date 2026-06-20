"""jobs/builder.py: Build ConversionJob lists from discovered audio files."""

from pathlib import Path
from typing import Optional

from audio.inspector import probe_many
from index.scanner import IndexRow
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


def enrich_index_rows(
    rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    ffprobe_binary: str,
    probe_workers: int,
) -> list[Path]:
    """Fill ``dest_path``, ``job_type``, and ``is_lossy`` on each IndexRow in place.

    Args:
        rows: List of IndexRow from the scanner. ``source_path``, ``file_size``,
            ``sidecar_files``, and ``mtime`` are already set; this fills the remaining fields.
        input_root: The root of the input path.
        source_root: If given, used as base for relative path computation.
        output_root: The root directory for output files.
        preset: The preset configuration to use.
        lossy_action: What to do with lossy source files (None = leave unspecified).
        no_lossy_check: If True, skip lossy probing entirely.
        ffprobe_binary: Path to the ffprobe binary.
        probe_workers: Number of workers for parallel probing.

    Returns:
        List of source paths that are lossy (for the lossy-action gate).
    """
    files = [Path(r.source_path) for r in rows]

    if no_lossy_check:
        is_lossy_map: dict[Path, Optional[bool]] = {f: None for f in files}
    else:
        is_lossy_map = probe_many(files, ffprobe_binary, probe_workers)

    lossy_files_found: list[Path] = []

    for row in rows:
        f = Path(row.source_path)
        is_lossy = is_lossy_map.get(f)

        if no_lossy_check:
            job_type: str = "convert"
        elif is_lossy:
            if lossy_action is None:
                job_type = "skip"
            elif lossy_action == LossyAction.LEAVE:
                job_type = "skip"
            elif lossy_action == LossyAction.COPY:
                job_type = "copy"
            elif lossy_action == LossyAction.CONVERT:
                job_type = "convert"
            else:
                job_type = "convert"
        else:
            job_type = "convert"

        # Mutate the row in place (IndexRow is frozen, so build a new one).
        # We rebuild the dataclass by replacing fields on the frozen object.
        object.__setattr__(row, "is_lossy", is_lossy)
        object.__setattr__(row, "job_type", job_type)

        outfile = compute_output_path(
            f,
            input_root,
            source_root,
            output_root,
            preset.ext,
        )
        object.__setattr__(row, "dest_path", str(outfile))

        if is_lossy:
            lossy_files_found.append(f)

    return lossy_files_found


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
    index_rows_out: list[IndexRow] | None = None,
    sidecar_map: dict[Path, str] | None = None,
) -> tuple[list[ConversionJob], list[Path]]:
    """Build ConversionJob list from discovered audio files.

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
        index_rows_out: If provided, enriched IndexRow entries (with final
            ``dest_path``, ``job_type``, and ``is_lossy``) are appended here
            for the temp index database.
        sidecar_map: If provided, maps each source ``Path`` to its
            newline-joined sidecar basenames (precomputed by the scanner).

    Returns:
        A tuple of (jobs, lossy_files_found) where:
        - jobs: List of ConversionJob objects for execution (skip jobs excluded from execution).
        - lossy_files_found: List of lossy file paths (for caller to abort if needed).
    """
    # Build minimal IndexRow placeholders for the scanner phase.
    if index_rows_out is not None:
        placeholder_rows: list[IndexRow] = []
        for f in files:
            stat = f.stat()
            sidecar_basenames = sidecar_map.get(f, "") if sidecar_map else ""
            placeholder_rows.append(
                IndexRow(
                    source_path=str(f),
                    dest_path="",
                    job_type="",
                    file_size=stat.st_size,
                    sidecar_files=sidecar_basenames,
                    mtime=stat.st_mtime,
                    is_lossy=None,
                )
            )
        lossy_files_found = enrich_index_rows(
            rows=placeholder_rows,
            input_root=input_root,
            source_root=source_root,
            output_root=output_root,
            preset=preset,
            lossy_action=lossy_action,
            no_lossy_check=no_lossy_check,
            ffprobe_binary=ffprobe_binary,
            probe_workers=probe_workers,
        )
        # Copy enriched rows to index_rows_out and convert to ConversionJob.
        for row in placeholder_rows:
            index_rows_out.append(row)
        jobs: list[ConversionJob] = []
        for row in placeholder_rows:
            is_lossy_val = row.is_lossy
            # reason field
            if no_lossy_check:
                reason = None
            elif is_lossy_val:
                if lossy_action is None:
                    reason = "lossy source, action=abort"
                elif lossy_action == LossyAction.LEAVE:
                    reason = "lossy source, action=leave"
                elif lossy_action == LossyAction.COPY:
                    reason = "lossy source, action=copy"
                else:
                    reason = "lossy source, action=convert"
            else:
                reason = None
            jobs.append(
                ConversionJob(
                    infile=Path(row.source_path),
                    outfile=Path(row.dest_path),
                    preset=preset,
                    job_type=row.job_type,
                    is_lossy_source=is_lossy_val,
                    reason=reason,
                )
            )
        return (jobs, lossy_files_found)

    # Legacy path: no index_rows_out — delegate to enrich_index_rows and convert.
    rows_for_enrich: list[IndexRow] = []
    for f in files:
        stat = f.stat()
        rows_for_enrich.append(
            IndexRow(
                source_path=str(f),
                dest_path="",
                job_type="",
                file_size=stat.st_size,
                sidecar_files="",
                mtime=stat.st_mtime,
                is_lossy=None,
            )
        )

    lossy_files_found = enrich_index_rows(
        rows=rows_for_enrich,
        input_root=input_root,
        source_root=source_root,
        output_root=output_root,
        preset=preset,
        lossy_action=lossy_action,
        no_lossy_check=no_lossy_check,
        ffprobe_binary=ffprobe_binary,
        probe_workers=probe_workers,
    )

    jobs = []
    for row in rows_for_enrich:
        jobs.append(
            ConversionJob(
                infile=Path(row.source_path),
                outfile=Path(row.dest_path),
                preset=preset,
                job_type=row.job_type,
                is_lossy_source=row.is_lossy,
                reason=None,
            )
        )
    return (jobs, lossy_files_found)
