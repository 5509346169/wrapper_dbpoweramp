"""main.py: Entry point for wrapper-dbpoweramp — orchestrates the full conversion pipeline."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from rich import print as rprint

from src.backends.registry import detect_backend_for_run, get_backend
from src.cli.args import parse_args, validate_args
from src.config.preset_loader import get_preset, load_presets
from src.config.settings_loader import load_settings
from src.exceptions import BackendError, PresetNotFoundError
from src.execution.runner import run_all
from src.history.db import ConversionDB, DBWriteQueue
from src.index.builder import IndexBuilder
from src.index.cleanup import cleanup_index
from src.index.scan_cache import ScanCache
from src.index.scanner import (
    IndexRow,
    _discover_audio_files,
    load_rows_from_cache,
    scan_with_progress,
)
from src.jobs.builder import enrich_index_rows_streaming
from src.models.types import Backend, ConversionJob, ExecutionMode, LossyAction
from src.pathing.resolver import validate_source_path
from src.ui.progress_view import NullProgressSink, RichProgressSink, VerboseProgressSink

# Module-level state used by the SIGINT/SIGTERM handlers below.
_run_interrupted: bool = False
_run_failed_count: int = 0


def _signal_handler(signum, frame) -> None:  # noqa: ANN001
    """Mark the run as interrupted (set a flag; do not raise from a signal handler)."""
    global _run_interrupted
    _run_interrupted = True
    rprint("\n[yellow]Interrupted.[/yellow]", file=sys.stderr)


def _resolve_backend_name(args, settings, preset) -> Backend:
    """Pick the backend for this run, honouring the CLI override and the auto-detect toggle."""
    cli_backend: Backend | None = None
    if args.backend is not None:
        cli_backend = Backend(args.backend)

    return detect_backend_for_run(
        cli_backend=cli_backend,
        settings=settings,
        preset=preset,
        platform=sys.platform,
        auto_detect_override=args.auto_detect_backend,
    )


def _build_index_only(
    args,
    settings,
    preset,
    backend,
    backend_name: Backend,
    verbose: bool = False,
) -> None:
    """
    Build and save an index database without performing any conversions.

    This mode scans the input directory, probes audio files for lossy detection,
    and writes all index rows to the user-specified database path before exiting.

    Args:
        verbose: If True, print per-file details to stdout during scanning and probing.
    """
    from src.index.scanner import _discover_audio_files, load_rows_from_cache, scan_with_progress
    from src.jobs.builder import enrich_index_rows_streaming
    from src.ui.progress_view import VerboseProgressSink

    # Install signal handlers
    old_sigint = signal.signal(signal.SIGINT, _signal_handler)
    old_sigterm = signal.signal(signal.SIGTERM, _signal_handler)

    # --build-index also benefits from the scan-cache: re-running it
    # against the same input reuses the previous scan and skips the
    # directory walk (probe still runs from scratch because the
    # --build-index output is the post-probe index).
    tmp_dir = Path("tmp")
    tmp_dir.mkdir(exist_ok=True)

    scan_cache: ScanCache | None = None
    cache_enabled = not getattr(args, "no_scan_cache", False)

    try:
        if cache_enabled:
            try:
                scan_cache = ScanCache.open_latest(tmp_dir, args.input, args.exclude)
            except OSError as exc:
                print(f"warning: could not read scan-cache: {exc}", file=sys.stderr)
                scan_cache = None

        if scan_cache is not None:
            rows = load_rows_from_cache(scan_cache)
            total_files = len(rows)
            if verbose:
                sink = VerboseProgressSink()
                sink.log_phase("Scanning")
                sink.log_file(
                    f"Cache hit: {total_files} file(s) from {scan_cache.db_path.name}"
                )
            else:
                sink = RichProgressSink()
                sink.start_phase("Scanning (cached)", total=total_files)
                for _ in range(total_files):
                    sink.advance()
            sink.stop()
            rprint(
                f" [green]{len(rows)} file(s) loaded from scan-cache "
                f"{scan_cache.db_path.name}[/green]"
            )
        else:
            # Cache miss — walk the directory and populate a fresh cache.
            audio_files = _discover_audio_files(args.input, args.exclude)
            total_files = len(audio_files)

            if cache_enabled:
                try:
                    scan_cache = ScanCache.create(tmp_dir, args.input, args.exclude)
                except OSError as exc:
                    print(
                        f"warning: could not create scan-cache: {exc}",
                        file=sys.stderr,
                    )
                    scan_cache = None

            if verbose:
                sink = VerboseProgressSink()
                sink.log_phase("Scanning")
                sink.log_file(f"Found {total_files} audio file(s)")
            else:
                sink = RichProgressSink()
                sink.start_phase("Scanning", total=total_files)
            rows, _ = scan_with_progress(
                input_path=args.input,
                excludes=args.exclude,
                preset=preset,
                progress=sink,
                audio_files=audio_files,
                cache=scan_cache,
            )
            sink.stop()

            rprint(f" [green]{len(rows)} file(s) found[/green]")
            if scan_cache is not None:
                rprint(f" [cyan]Scan cache:[/cyan] {scan_cache.db_path}")

        if not rows:
            print("No audio files found.")
            return

        # Determine input_root and source_root
        if args.input.is_file():
            input_root = args.input.parent
        else:
            input_root = args.input

        source_root = args.source_path if args.source_path is not None else None

        # Build the index to user-specified path.
        # Note: enrich_index_rows_streaming owns the progress bar lifecycle —
        # it calls start_phase("Probing", ...) internally so the bar total
        # can be set to include the mutagen tier. We just hand it the sink.
        if verbose:
            sink = VerboseProgressSink()
            sink.log_phase("Probing")
        else:
            sink = RichProgressSink()

        lossy_action: LossyAction | None = None
        if args.lossy_action is not None:
            lossy_action = LossyAction(args.lossy_action)

        index_builder = IndexBuilder(args.build_index)

        enrich_index_rows_streaming(
            scan_rows=rows,
            input_root=input_root,
            source_root=source_root,
            output_root=args.output,
            preset=preset,
            lossy_action=lossy_action,
            no_lossy_check=args.no_lossy_check,
            probe_workers=settings.execution.probe_workers,
            progress=sink,
            index_builder=index_builder,
        )

        index_builder.commit()
        sink.stop()

        # Print summary
        summary = index_builder.get_summary()
        rprint()
        rprint(f"[green]Index built successfully:[/green] {args.build_index}")
        rprint(f"  Total files: {summary['total']}")
        rprint(f"  Total size: {_format_bytes(summary['total_bytes'])}")
        rprint(f"  Lossy files: {summary['lossy']}")
        for job_type, count in summary["by_type"].items():
            rprint(f"  {job_type}: {count}")

        index_builder.close()

    finally:
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)
        if scan_cache is not None:
            try:
                scan_cache.close()
            except Exception:
                pass


def _run_from_index(
    args,
    settings,
    preset,
    backend,
    backend_name: Backend,
) -> None:
    """
    Run conversions using a pre-built index database, skipping filesystem scan/probe phases.
    """
    global _run_interrupted, _run_failed_count

    # Open the existing index
    try:
        index_builder = IndexBuilder.from_existing(args.index)
    except FileNotFoundError:
        print(f"error: index database not found: {args.index}", file=sys.stderr)
        sys.exit(1)

    source_rows = list(index_builder.iter_rows())
    index_builder.close()

    if not source_rows:
        print("Index is empty.")
        return

    # Print summary
    index_builder = IndexBuilder.from_existing(args.index)
    summary_info = index_builder.get_summary()
    index_builder.close()

    print(f"Loaded index: {args.index}")
    print(f"  Total files: {summary_info['total']}")
    print(f"  Total size: {_format_bytes(summary_info['total_bytes'])}")
    print(f"  Lossy files: {summary_info['lossy']}")

    # Build ConversionJob list from index rows
    def _row_to_job(row: IndexRow) -> ConversionJob:
        is_lossy_val = row.is_lossy
        if args.no_lossy_check:
            reason = None
        elif is_lossy_val:
            if args.lossy_action is None:
                reason = "lossy source, action=abort"
            elif args.lossy_action == "leave":
                reason = "lossy source, action=leave"
            elif args.lossy_action == "copy":
                reason = "lossy source, action=copy"
            else:
                reason = "lossy source, action=convert"
        else:
            reason = None
        return ConversionJob(
            infile=Path(row.source_path),
            outfile=Path(row.dest_path),
            preset=preset,
            job_type=row.job_type,
            is_lossy_source=is_lossy_val,
            reason=reason,
        )

    jobs = [_row_to_job(r) for r in source_rows]

    # Lossy gate check
    lossy_count = summary_info["lossy"]
    if lossy_count > 0 and args.lossy_action is None and not args.no_lossy_check:
        print()
        print(f"Lossy source files found ({lossy_count}). You must specify --lossy-action to proceed.")
        print("Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert")
        sys.exit(1)

    # Install signal handlers
    old_sigint = signal.signal(signal.SIGINT, _signal_handler)
    old_sigterm = signal.signal(signal.SIGTERM, _signal_handler)

    conv_summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
    exc_info: str | None = None

    try:
        db_path = args.db if args.db is not None else Path(settings.history.db_path)

        workers = args.workers if args.workers is not None else settings.execution.default_workers
        worker_model = args.worker_model if args.worker_model is not None else settings.execution.worker_model
        execution_mode = getattr(args, "execution_mode", "hybrid")

        # Pre-filter: identify already-converted files before starting any progress bar.
        pending_jobs: list[ConversionJob] = []
        skipped_jobs: list[ConversionJob] = []
        if not args.force:
            db = ConversionDB(db_path)
            for job in jobs:
                dest_exists = job.outfile.exists()
                dest_size = job.outfile.stat().st_size if dest_exists else None
                if db.should_skip(
                    str(job.infile), str(job.outfile), job_type=job.job_type,
                    dest_file_exists=dest_exists, dest_file_size=dest_size,
                ):
                    skipped_jobs.append(job)
                else:
                    pending_jobs.append(job)
            db.close()
        else:
            pending_jobs = list(jobs)
            skipped_jobs = []

        if execution_mode == "phased":
            prefilter_skips = skipped_jobs
            pending_for_pool = [j for j in pending_jobs if j.job_type != "skip"]
        else:
            prefilter_skips = []
            pending_for_pool = pending_jobs

        total_bytes = summary_info["total_bytes"]

        if args.verbose:
            sink = NullProgressSink()
            progress_active = False
            if prefilter_skips:
                print(f"[Skipping] {len(prefilter_skips)} already-converted file(s)")
            phases = _run_jobs_by_phase(pending_for_pool, execution_mode)
            for phase_label, batch in phases:
                print(f"Phase — {phase_label} ({len(batch)} file(s))")
            if phases:
                phase_summary, _, _, write_queue = run_all(
                    jobs=[j for _, batch in phases for j in batch],
                    backend=backend,
                    db_path=str(db_path),
                    force=args.force,
                    workers=workers,
                    worker_model=worker_model,
                    verbose=args.verbose,
                    progress=sink,
                    print_to_terminal=args.verbose,
                )
            else:
                phase_summary = {"success": 0, "skipped": 0, "failed": 0}
                write_queue = DBWriteQueue(Path(db_path), worker_model)
            conv_summary = phase_summary
        else:
            sink = RichProgressSink(total_bytes=total_bytes)
            if prefilter_skips:
                sink.start_phase("Skipping", total=len(prefilter_skips))
                for job in prefilter_skips:
                    sink.advance()
                    if hasattr(sink, "log_file"):
                        sink.log_file(f"  {job.infile.name}")
                sink.stop_phase()
                sink.log(f"Skipped {len(prefilter_skips)} already-converted file(s)")
            phases = _run_jobs_by_phase(pending_for_pool, execution_mode)
            phase_summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
            write_queue: DBWriteQueue | None = None
            for phase_label, batch in phases:
                sink.start_phase(phase_label, total=len(batch))
                phase_result, futures, events, write_queue = run_all(
                    jobs=batch,
                    backend=backend,
                    db_path=str(db_path),
                    force=args.force,
                    workers=workers,
                    worker_model=worker_model,
                    verbose=args.verbose,
                    progress=sink,
                    print_to_terminal=args.verbose,
                )
                if workers > 1:
                    from concurrent.futures import as_completed as _as_completed
                    from src.execution.runner import _drain_events_into_ui
                    from src.ui.progress_view import SubtaskID

                    job_tasks: dict[str, SubtaskID] = {}
                    remaining = list(futures)
                    while remaining:
                        _drain_events_into_ui(events, sink, job_tasks)
                        for future in list(_as_completed(remaining)):
                            remaining.remove(future)
                            status, infile_name, error_msg = future.result()
                            if status == "SUCCESS":
                                phase_result["success"] += 1
                            elif status == "SKIPPED":
                                phase_result["skipped"] += 1
                            else:
                                phase_result["failed"] += 1
                for k in phase_summary:
                    phase_summary[k] += phase_result.get(k, 0)
                sink.stop_phase()
            progress_active = True
            conv_summary = phase_summary

        if progress_active:
            sink.stop()
        if write_queue is not None:
            write_queue.flush()

        conv_summary["skipped"] += len(prefilter_skips)

        print()
        print(
            f"Done.  Success: {conv_summary['success']}  "
            f"Skipped: {conv_summary['skipped']}  Failed: {conv_summary['failed']}"
        )

    except Exception as exc:
        exc_info = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        global _run_failed_count
        _run_failed_count = conv_summary.get("failed", 0)

        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)


def _format_bytes(num_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if num_bytes >= 1 << 30:
        return f"{num_bytes / (1 << 30):.1f} GiB"
    if num_bytes >= 1 << 20:
        return f"{num_bytes / (1 << 20):.1f} MiB"
    if num_bytes >= 1 << 10:
        return f"{num_bytes / (1 << 10):.1f} KiB"
    return f"{num_bytes} B"


def _run_jobs_by_phase(
    jobs: list[ConversionJob],
    execution_mode: str,
) -> list[tuple[str, list[ConversionJob]]]:
    """Split jobs into sequential phases according to execution_mode.

    In 'hybrid' mode returns a single batch containing all jobs (unchanged behaviour).
    In 'phased' mode returns three batches in strict order: skip → copy → convert.
    Empty job-type lists are omitted from the result.
    """
    if execution_mode == "hybrid":
        return [("convert", jobs)]

    phased: list[tuple[str, list[ConversionJob]]] = []
    for jtype, label in [("skip", "Skipping"), ("copy", "Copying"), ("convert", "Converting")]:
        batch = [j for j in jobs if j.job_type == jtype]
        if batch:
            phased.append((label, batch))
    return phased


def _main() -> None:
    # 1. Parse + validate args
    args = parse_args()
    validate_args(args)

    # 2. Load config + presets
    settings = load_settings(Path("settings.yaml"))
    presets = load_presets(Path("presets.yaml"))

    try:
        preset = get_preset(presets, args.preset)
    except PresetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 3. Resolve backend via auto-detect or CLI override
    backend_name = _resolve_backend_name(args, settings, preset)
    try:
        backend = get_backend(backend_name, settings)
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 3a. Preset compatibility gate — the chosen backend must support this preset.
    if not backend.supports(preset):
        print(
            f"error: backend '{backend_name.value}' does not support preset '{preset.name}'.\n"
            f"  Choose a different backend with --backend, or pick a preset that supports "
            f"'{backend_name.value}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3b. Handle --build-index mode (build index and exit)
    if args.build_index is not None:
        _build_index_only(args, settings, preset, backend, backend_name, verbose=args.verbose)
        return

    # 3c. Handle --index mode (use existing index and run conversions)
    if args.index is not None:
        _run_from_index(args, settings, preset, backend, backend_name)
        return

    # 4. Validate source_path if given
    if args.source_path is not None:
        validate_source_path(args.input, args.source_path)

    # 5. Set up the temp index DB BEFORE the scan so we capture every file,
    #    including those the lossy gate may skip. The DB is removed on a clean
    #    exit and kept on failure (for post-mortem debugging).
    #    Also set up the scan-cache: a small per-run SQLite snapshot of the
    #    discovered files so the probe phase can skip the directory walk.
    tmp_dir = Path("tmp")
    try:
        tmp_dir.mkdir(exist_ok=True)
    except OSError as exc:
        print(f"warning: could not create {tmp_dir} for index DB: {exc}", file=sys.stderr)
        tmp_dir = None  # type: ignore[assignment]

    index_db_path: Path | None = tmp_dir / "index.db" if tmp_dir is not None else None

    # 6. Install signal handlers so we can keep the index on Ctrl+C / SIGTERM.
    old_sigint = signal.signal(signal.SIGINT, _signal_handler)
    old_sigterm = signal.signal(signal.SIGTERM, _signal_handler)

    summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
    exc_info: str | None = None

    # Track the scan-cache so we can close it on exit (regardless of outcome).
    scan_cache: ScanCache | None = None
    scan_cache_loaded_from_disk: bool = False

    try:
        # 7. Scan phase.
        #    Two-tier strategy:
        #      a) If a matching scan-cache file already exists in ./tmp/ (from a
        #         previous run on the same input+excludes), load rows from it
        #         — skipping the directory walk entirely.
        #      b) Otherwise, walk the directory with _discover_audio_files,
        #         pass the cache to scan_with_progress so it gets populated
        #         as a side-effect, then proceed.
        #    --no-scan-cache disables (a) and forces a fresh walk every run.
        cache_enabled = (
            not getattr(args, "no_scan_cache", False)
            and tmp_dir is not None
            and args.input is not None
        )

        if cache_enabled:
            try:
                scan_cache = ScanCache.open_latest(
                    tmp_dir, args.input, args.exclude
                )
            except OSError as exc:
                print(
                    f"warning: could not read scan-cache: {exc}",
                    file=sys.stderr,
                )
                scan_cache = None

        if scan_cache is not None:
            # Cache hit — skip the directory walk entirely.
            cached_rows = load_rows_from_cache(scan_cache)
            total_files = len(cached_rows)
            scan_cache_loaded_from_disk = True
            rows = cached_rows
            sidecar_map: dict[Path, str] = {
                Path(r.source_path): r.sidecar_files for r in rows
            }

            if args.verbose:
                sink = VerboseProgressSink()
                sink.log_phase("Scanning")
                sink.log_file(f"Cache hit: {total_files} file(s) from {scan_cache.db_path.name}")
            else:
                sink = RichProgressSink()
                sink.start_phase("Scanning (cached)", total=total_files)
                # Advance the bar to completion instantly — the work was
                # already done in the previous run that wrote the cache.
                for _ in range(total_files):
                    sink.advance()
            sink.stop()
            rprint(
                f" [green]{len(rows)} file(s) loaded from scan-cache "
                f"{scan_cache.db_path.name}[/green]"
            )
        else:
            # Cache miss (or cache disabled) — walk the directory and
            # populate the cache as we go.
            audio_files = _discover_audio_files(args.input, args.exclude)
            total_files = len(audio_files)

            if cache_enabled and tmp_dir is not None:
                try:
                    scan_cache = ScanCache.create(
                        tmp_dir, args.input, args.exclude
                    )
                except OSError as exc:
                    print(
                        f"warning: could not create scan-cache: {exc}",
                        file=sys.stderr,
                    )
                    scan_cache = None

            if args.verbose:
                sink = VerboseProgressSink()
                sink.log_phase("Scanning")
                sink.log_file(f"Found {total_files} audio file(s)")
            else:
                sink = RichProgressSink()
                sink.start_phase("Scanning", total=total_files)
            rows, sidecar_map = scan_with_progress(
                input_path=args.input,
                excludes=args.exclude,
                preset=preset,
                progress=sink,
                audio_files=audio_files,
                cache=scan_cache,
            )
            sink.stop()

            rprint(f" [green]{len(rows)} file(s) found[/green]")
            if scan_cache is not None:
                rprint(f" [cyan]Scan cache:[/cyan] {scan_cache.db_path}")

        if not rows:
            print("No audio files found.")
            return

        # Determine input_root and source_root for path computation.
        input_root: Path
        source_root: Path | None

        if args.input.is_file():
            input_root = args.input.parent
        else:
            input_root = args.input

        if args.source_path is not None:
            source_root = args.source_path
        else:
            source_root = None

        # 8. Enrich index rows: lossy probe + output path + job type.
        #    Keep the progress bar alive — scanning has finished and probing is
        #    the expensive step.  Rows are written to the index DB as each probe
        #    result arrives, so the DB is a real-time snapshot rather than a
        #    deferred write.
        lossy_action: LossyAction | None = None
        if args.lossy_action is not None:
            lossy_action = LossyAction(args.lossy_action)

        index_builder = None
        if index_db_path is not None:
            try:
                index_builder = IndexBuilder(index_db_path)
            except OSError as exc:
                print(f"warning: could not open index DB {index_db_path}: {exc}", file=sys.stderr)

        lossy_files_found = enrich_index_rows_streaming(
            scan_rows=rows,
            input_root=input_root,
            source_root=source_root,
            output_root=args.output,
            preset=preset,
            lossy_action=lossy_action,
            no_lossy_check=args.no_lossy_check,
            probe_workers=settings.execution.probe_workers,
            progress=sink,
            index_builder=index_builder,
        )

        if index_builder is not None:
            index_builder.commit()
            rprint(f"[cyan]Index:[/cyan] {index_db_path}")
            # Re-read the DB as the source of truth — all rows are already written
            # by the streaming probe, so this is a fast snapshot of what landed.
            index_builder.close()
            db_rows = list(IndexBuilder(index_db_path).iter_rows())
            source_rows: list[IndexRow] = db_rows
            sink = RichProgressSink()
        else:
            # Index DB unavailable; use the in-memory enriched rows.
            source_rows = rows

        # 10. Build the ConversionJob list from the source of truth.
        def _row_to_job(row: IndexRow) -> ConversionJob:
            is_lossy_val = row.is_lossy
            if args.no_lossy_check:
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
            return ConversionJob(
                infile=Path(row.source_path),
                outfile=Path(row.dest_path),
                preset=preset,
                job_type=row.job_type,
                is_lossy_source=is_lossy_val,
                reason=reason,
            )

        jobs = [_row_to_job(r) for r in source_rows]

        # 11. Lossy gate
        if (
            lossy_files_found
            and args.lossy_action is None
            and not args.dry_run
            and not args.list_lossy
            and not args.no_lossy_check
        ):
            print()
            print("Lossy source files found. You must specify --lossy-action to proceed.")
            print(f"Found {len(lossy_files_found)} lossy file(s):")
            for f in lossy_files_found:
                print(f"  {f}")
            print()
            print("Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert")
            sys.exit(1)

        # 11a. --list-lossy: print lossy files and exit
        if args.list_lossy:
            if not lossy_files_found:
                print("No lossy files found.")
            else:
                for f in lossy_files_found:
                    print(f)
            return

        # 11b. --dry-run: print job list and exit
        if args.dry_run:
            execution_mode = getattr(args, "execution_mode", "hybrid")
            phases = _run_jobs_by_phase(jobs, execution_mode)
            print("Dry run — jobs that would be executed:")
            print()
            if execution_mode == "phased":
                total_phases = len(phases)
                for i, (phase_label, batch) in enumerate(phases, 1):
                    print(f"Phase {i}/{total_phases} — {phase_label} ({len(batch)} job(s))")
                    for job in batch:
                        lossy_marker = " [LOSSY]" if job.is_lossy_source else ""
                        print(f"  {job.infile} -> {job.outfile}  [{job.job_type}]{lossy_marker}")
                        if job.reason:
                            print(f"    reason: {job.reason}")
            else:
                for job in jobs:
                    lossy_marker = " [LOSSY]" if job.is_lossy_source else ""
                    print(f"  {job.infile} -> {job.outfile}  [{job.job_type}]{lossy_marker}")
                    if job.reason:
                        print(f"    reason: {job.reason}")
            print()
            print(f"Total: {len(jobs)} job(s)")
            return

        # 12. Real execution
        db_path = args.db if args.db is not None else Path(settings.history.db_path)

        workers = args.workers if args.workers is not None else settings.execution.default_workers
        worker_model = args.worker_model if args.worker_model is not None else settings.execution.worker_model
        execution_mode = getattr(args, "execution_mode", "hybrid")

        # Pre-filter: identify already-converted files before starting any progress bar.
        pending_jobs: list[ConversionJob] = []
        skipped_jobs: list[ConversionJob] = []
        if not args.force:
            db = ConversionDB(db_path)
            for job in jobs:
                dest_exists = job.outfile.exists()
                dest_size = job.outfile.stat().st_size if dest_exists else None
                if db.should_skip(
                    str(job.infile), str(job.outfile), job_type=job.job_type,
                    dest_file_exists=dest_exists, dest_file_size=dest_size,
                ):
                    skipped_jobs.append(job)
                else:
                    pending_jobs.append(job)
            db.close()
        else:
            pending_jobs = list(jobs)
            skipped_jobs = []

        # In phased mode, skip-jobs are handled as a dedicated phase and are not
        # included in pending_jobs for the pool. In hybrid mode they are already
        # filtered out above (they are record-only skips that ran through the pool).
        if execution_mode == "phased":
            prefilter_skips = skipped_jobs
            pending_for_pool = [j for j in pending_jobs if j.job_type != "skip"]
        else:
            prefilter_skips = []
            pending_for_pool = pending_jobs

        total_bytes = sum(row.file_size for row in rows)

        # In verbose mode: no progress bar, print phase labels directly.
        if args.verbose:
            sink = NullProgressSink()
            progress_active = False
            if prefilter_skips:
                print(f"[Skipping] {len(prefilter_skips)} already-converted file(s)")
            phases = _run_jobs_by_phase(pending_for_pool, execution_mode)
            for phase_label, batch in phases:
                print(f"Phase — {phase_label} ({len(batch)} file(s))")
            if phases:
                phase_summary, _, _, write_queue = run_all(
                    jobs=[j for _, batch in phases for j in batch],
                    backend=backend,
                    db_path=str(db_path),
                    force=args.force,
                    workers=workers,
                    worker_model=worker_model,
                    verbose=args.verbose,
                    progress=sink,
                    print_to_terminal=args.verbose,
                )
            else:
                phase_summary = {"success": 0, "skipped": 0, "failed": 0}
                write_queue = DBWriteQueue(Path(db_path), worker_model)
            summary = phase_summary
        else:
            sink = RichProgressSink(total_bytes=total_bytes)
            if prefilter_skips:
                sink.start_phase("Skipping", total=len(prefilter_skips))
                for job in prefilter_skips:
                    sink.advance()
                    if hasattr(sink, "log_file"):
                        sink.log_file(f"  {job.infile.name}")
                sink.stop_phase()
                sink.log(f"Skipped {len(prefilter_skips)} already-converted file(s)")
            phases = _run_jobs_by_phase(pending_for_pool, execution_mode)
            phase_summary: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}
            write_queue: DBWriteQueue | None = None
            for phase_label, batch in phases:
                total_phase_bytes = sum(j.outfile.stat().st_size for j in batch if j.outfile.exists())
                remaining_bytes = total_bytes - total_phase_bytes
                sink.start_phase(phase_label, total=len(batch))
                conv_summary, futures, events, write_queue = run_all(
                    jobs=batch,
                    backend=backend,
                    db_path=str(db_path),
                    force=args.force,
                    workers=workers,
                    worker_model=worker_model,
                    verbose=args.verbose,
                    progress=sink,
                    print_to_terminal=args.verbose,
                )
                if workers > 1:
                    from concurrent.futures import as_completed as _as_completed
                    from src.execution.runner import _drain_events_into_ui
                    from src.ui.progress_view import SubtaskID

                    job_tasks: dict[str, SubtaskID] = {}
                    remaining = list(futures)
                    while remaining:
                        _drain_events_into_ui(events, sink, job_tasks)
                        for future in list(_as_completed(remaining)):
                            remaining.remove(future)
                            status, infile_name, error_msg = future.result()
                            if status == "SUCCESS":
                                conv_summary["success"] += 1
                            elif status == "SKIPPED":
                                conv_summary["skipped"] += 1
                            else:
                                conv_summary["failed"] += 1
                for k in phase_summary:
                    phase_summary[k] += conv_summary.get(k, 0)
                sink.stop_phase()
            progress_active = True
            summary = phase_summary

        if progress_active:
            sink.stop()
        if write_queue is not None:
            write_queue.flush()

        # Add pre-filtered skips to the summary.
        summary["skipped"] += len(prefilter_skips)

        # 13. Print final summary
        print()
        print(
            f"Done.  Success: {summary['success']}  "
            f"Skipped: {summary['skipped']}  Failed: {summary['failed']}"
        )

    except Exception as exc:
        exc_info = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        # Capture failed count for cleanup_index even on early returns.
        global _run_failed_count
        _run_failed_count = summary.get("failed", 0)

        # Restore original signal handlers
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

        # 14. Decide whether to keep or delete the temp index DB
        cleanup_index(
            db_path=index_db_path,
            failed_count=_run_failed_count,
            exception_info=exc_info,
            interrupted=_run_interrupted,
        )

        # 15. Close the scan-cache (if any). Unlike the index DB, the
        #     scan-cache is kept on disk across runs — it's the per-run
        #     snapshot that makes the next probe phase free.
        if scan_cache is not None:
            try:
                scan_cache.close()
            except Exception:
                pass


if __name__ == "__main__":
    _main()
