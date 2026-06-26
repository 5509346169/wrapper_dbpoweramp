"""jobs/build_jobs.py: Build ConversionJob lists from discovered audio files."""

from pathlib import Path

from src.index.scanner import IndexRow
from src.models.types import ConversionJob, LossyAction, PresetConfig

from src.jobs.enrich import enrich_index_rows


def _placeholder_rows_from_files(
    files: list[Path],
    sidecar_map: dict[Path, str] | None,
) -> list[IndexRow]:
    """Build minimal IndexRow placeholders for a list of source Paths.

    Used when the caller wants enriched IndexRow entries for the temp
    index database alongside the ConversionJob list.
    """
    rows: list[IndexRow] = []
    for f in files:
        stat = f.stat()
        sidecar_basenames = sidecar_map.get(f, "") if sidecar_map else ""
        rows.append(
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
    return rows


def _reason_for_lossy(
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
) -> str | None:
    """Compose the human-readable reason for a ConversionJob."""
    if no_lossy_check:
        return None
    if not is_lossy_val:
        return None
    if lossy_action is None:
        return "lossy source, action=abort"
    if lossy_action == LossyAction.LEAVE:
        return "lossy source, action=leave"
    if lossy_action == LossyAction.COPY:
        return "lossy source, action=copy"
    return "lossy source, action=convert"


def build_jobs(
    files: list[Path],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
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
        probe_workers: Number of workers for parallel probing (mutagen I/O).
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
    placeholder_rows = _placeholder_rows_from_files(files, sidecar_map)
    lossy_files_found = enrich_index_rows(
        rows=placeholder_rows,
        input_root=input_root,
        source_root=source_root,
        output_root=output_root,
        preset=preset,
        lossy_action=lossy_action,
        no_lossy_check=no_lossy_check,
        probe_workers=probe_workers,
    )

    if index_rows_out is not None:
        index_rows_out.extend(placeholder_rows)

    jobs: list[ConversionJob] = []
    for row in placeholder_rows:
        is_lossy_val = row.is_lossy
        reason = _reason_for_lossy(is_lossy_val, lossy_action, no_lossy_check)
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
    return jobs, lossy_files_found
