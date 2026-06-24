"""jobs/builder.py: Build ConversionJob lists from discovered audio files."""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from src.index.builder import IndexBuilder
from src.index.scanner import IndexRow, _discover_audio_files
from src.models.types import AUDIO_EXTENSIONS, ConversionJob, LossyAction, PresetConfig
from src.pathing.resolver import compute_output_path


def _classify(
    row: IndexRow,
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
) -> None:
    """Classify a single row and write it to the index DB immediately.

    Note: mutates ``row`` in-place via ``object.__setattr__`` (IndexRow is frozen).
    """
    f = Path(row.source_path)

    if no_lossy_check:
        job_type: str = "convert"
    elif is_lossy_val:
        if lossy_action is None:
            job_type = "skip"
        elif lossy_action == LossyAction.LEAVE:
            job_type = "skip"
        elif lossy_action == LossyAction.COPY:
            job_type = "copy"
        else:
            job_type = "convert"
    else:
        job_type = "convert"

    object.__setattr__(row, "is_lossy", is_lossy_val)
    object.__setattr__(row, "job_type", job_type)

    outfile = compute_output_path(
        f,
        input_root,
        source_root,
        output_root,
        preset.ext,
    )
    object.__setattr__(row, "dest_path", str(outfile))


def enrich_index_rows_streaming(
    scan_rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
    progress: "ProgressSink",
    index_builder: IndexBuilder | None,
) -> list[Path]:
    """Stream-probe files, write rows to the index DB incrementally, and report live progress.

    Detection cascade (fastest first):
      1. Extension — deterministic, zero I/O (most files resolved here).
      2. Folder-name heuristic — zero I/O (e.g. "[256Kbps-AAC]" in a parent dir).
      3. mutagen metadata probe — only for ambiguous extensions (.m4a, etc.).

    Progress is advanced once per file as it is resolved — either immediately
    (tiers 1-2, main thread) or as the mutagen future completes (tier 3, thread pool).

    Args:
        scan_rows:     Rows from the scanner (source_path, file_size, sidecar_files, mtime set).
        progress:      A ``ProgressSink`` whose ``advance()`` is called after each result.
        index_builder: If provided, each completed row is written to the DB immediately.
        (all other args are identical to ``enrich_index_rows`` — see that docstring).

    Returns:
        List of source paths that are lossy (for the lossy-action gate).
    """
    from concurrent.futures import Future, as_completed

    from src.audio.inspector import (
        _classify_by_ext_and_folder,
        _is_lossy_by_mutagen,
    )

    total = len(scan_rows)
    progress.start_phase("Probing", total=total)

    # Build a lookup from Path -> row for O(1) assignment after each result.
    path_to_row: dict[Path, IndexRow] = {Path(r.source_path): r for r in scan_rows}
    files = list(path_to_row.keys())

    lossy_files_found: list[Path] = []

    if no_lossy_check:
        # Fast path: skip all detection, treat everything as lossless.
        for row in scan_rows:
            _classify(
                row, None, lossy_action, no_lossy_check,
                input_root, source_root, output_root, preset,
            )
            if index_builder is not None:
                index_builder.add(row)
            if hasattr(progress, "log_file"):
                progress.log_file(f"  {Path(row.source_path).name} -> convert")
            progress.advance()
    else:
        # Tier 1 + 2 synchronously on the main thread (no I/O).
        classified = _classify_by_ext_and_folder(files)

        # Immediately resolve files where tiers 1-2 gave an answer.
        ambiguous_files: list[Path] = []
        for f in files:
            result = classified[f]
            row = path_to_row[f]
            if result is not None:
                _classify(
                    row, result, lossy_action, no_lossy_check,
                    input_root, source_root, output_root, preset,
                )
                if index_builder is not None:
                    index_builder.add(row)
                if result:
                    lossy_files_found.append(f)
                if hasattr(progress, "log_file"):
                    progress.log_file(f"  {f.name} -> {row.job_type} {'[LOSSY]' if result else ''}")
            else:
                ambiguous_files.append(f)
            progress.advance()

        # Tier 3: mutagen only for ambiguous files.
        if ambiguous_files:
            if hasattr(progress, "log_phase"):
                progress.log_phase("Probing (mutagen)")
            else:
                progress.log(f"Probing {len(ambiguous_files)} ambiguous files with mutagen ({probe_workers} workers)...")
            _LOG_INTERVAL = 10
            _tier3_done = 0

            def probe_one(file: Path) -> tuple[Path, bool]:
                return (file, _is_lossy_by_mutagen(file))

            with ThreadPoolExecutor(max_workers=probe_workers) as executor:
                future_map: dict[Future, Path] = {
                    executor.submit(probe_one, f): f for f in ambiguous_files
                }
                for future in as_completed(future_map):
                    infile = future_map[future]
                    try:
                        _, is_lossy_val = future.result()
                    except Exception:
                        # ProbeError — treat as lossless so the conversion backend
                        # surfaces the real error rather than skipping the file.
                        is_lossy_val = None

                    row = path_to_row[infile]
                    _classify(
                        row, is_lossy_val, lossy_action, no_lossy_check,
                        input_root, source_root, output_root, preset,
                    )
                    if index_builder is not None:
                        index_builder.add(row)
                    if is_lossy_val:
                        lossy_files_found.append(infile)
                    if hasattr(progress, "log_file"):
                        progress.log_file(f"  {infile.name} -> {row.job_type} {'[LOSSY]' if is_lossy_val else ''}")
                    progress.advance()
                    _tier3_done += 1
                    if _tier3_done % _LOG_INTERVAL == 0:
                        total_done = total - len(ambiguous_files) + _tier3_done
                        if not hasattr(progress, "log_file"):
                            progress.log(f"Probing {total_done}/{total} ({total_done * 100 // total}%)...")

            if not hasattr(progress, "log_file"):
                progress.log(f"Probing done. {len(lossy_files_found)} lossy file(s) found.")
            elif len(lossy_files_found) > 0:
                progress.log_file(f"  Total lossy files: {len(lossy_files_found)}")

    progress.stop()
    return lossy_files_found


def enrich_index_rows(
    rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
) -> list[Path]:
    """Fill ``dest_path``, ``job_type``, and ``is_lossy`` on each IndexRow in place.

    This is the blocking convenience wrapper. For live progress and incremental index
    DB writes, use :func:`enrich_index_rows_streaming` instead.

    Returns:
        List of source paths that are lossy (for the lossy-action gate).
    """
    files = [Path(r.source_path) for r in rows]

    if no_lossy_check:
        is_lossy_map: dict[Path, bool | None] = {f: None for f in files}
    else:
        from src.audio.inspector import probe_many
        is_lossy_map = probe_many(files, probe_workers)

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
