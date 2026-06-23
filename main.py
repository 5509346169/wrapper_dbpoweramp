"""main.py: Entry point for wrapper-dbpoweramp — orchestrates the full conversion pipeline."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from src.backends.registry import detect_backend_for_run, get_backend
from src.cli.args import parse_args, validate_args
from src.config.preset_loader import get_preset, load_presets
from src.config.settings_loader import load_settings
from src.exceptions import BackendError, PresetNotFoundError
from src.execution.runner import run_all
from src.history.db import ConversionDB
from src.index.builder import IndexBuilder
from src.index.cleanup import cleanup_index
from src.index.scanner import (
    IndexRow,
    _discover_audio_files,
    scan_with_progress,
)
from src.jobs.builder import enrich_index_rows_streaming
from src.models.types import Backend, ConversionJob, LossyAction
from src.pathing.resolver import validate_source_path
from src.ui.progress_view import RichProgressSink

# Module-level state used by the SIGINT/SIGTERM handlers below.
_run_interrupted: bool = False
_run_failed_count: int = 0


def _signal_handler(signum, frame) -> None:  # noqa: ANN001
    """Mark the run as interrupted (set a flag; do not raise from a signal handler)."""
    global _run_interrupted
    _run_interrupted = True
    print("\n[yellow]Interrupted.[/yellow]", file=sys.stderr)


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

    # 4. Validate source_path if given
    if args.source_path is not None:
        validate_source_path(args.input, args.source_path)

    # 5. Set up the temp index DB BEFORE the scan so we capture every file,
    #    including those the lossy gate may skip. The DB is removed on a clean
    #    exit and kept on failure (for post-mortem debugging).
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

    summary: dict[str, int] = {}
    exc_info: str | None = None

    try:
        # 7. Scan phase with a progress bar.
        # Use _discover_audio_files once to get both the count and the iterator;
        # scan_with_progress walks the same list and calls progress.advance()
        # per file, eliminating the double rglob.
        audio_files = _discover_audio_files(args.input, args.exclude)
        total_files = len(audio_files)

        sink = RichProgressSink()
        sink.start_phase("Scanning", total=total_files)
        rows, sidecar_map = scan_with_progress(
            input_path=args.input,
            excludes=args.exclude,
            preset=preset,
            progress=sink,
        )
        sink.stop()

        print(f" [green]{len(rows)} file(s) found[/green]")

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
            print(f"[cyan]Index:[/cyan] {index_db_path}")
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
            print("Dry run — jobs that would be executed:")
            print()
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
        db = ConversionDB(db_path)

        workers = args.workers if args.workers is not None else settings.execution.default_workers
        worker_model = args.worker_model if args.worker_model is not None else settings.execution.worker_model

        total_bytes = sum(row.file_size for row in rows)
        sink = RichProgressSink(total_bytes=total_bytes)
        sink.start_phase("Converting", total=len(jobs))
        summary, futures, events = run_all(
            jobs=jobs,
            backend=backend,
            db=db,
            force=args.force,
            workers=workers,
            worker_model=worker_model,
            verbose=args.verbose,
            progress=sink,
        )

        # In parallel mode, drain the event queue until all futures complete.
        if workers > 1:
            from concurrent.futures import as_completed as _as_completed
            from src.execution.runner import _drain_events_into_ui

            remaining = list(futures)
            while remaining:
                _drain_events_into_ui(events, sink)
                for future in list(_as_completed(remaining)):
                    remaining.remove(future)
                    status, infile_name, error_msg = future.result()
                    if status == "SUCCESS":
                        summary["success"] += 1
                    elif status == "SKIPPED":
                        summary["skipped"] += 1
                    else:
                        summary["failed"] += 1
                    sink.advance()

        sink.stop()

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


if __name__ == "__main__":
    _main()
