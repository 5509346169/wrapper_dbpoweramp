"""main.py: Entry point for wrapper-dbpoweramp — orchestrates the full conversion pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

from backends.registry import get_backend, resolve_backend_for_run
from cli.args import parse_args, validate_args
from config.preset_loader import get_preset, load_presets
from config.settings_loader import load_settings
from exceptions import PresetNotFoundError
from execution.runner import run_all
from history.db import ConversionDB
from jobs.builder import build_jobs, discover_audio_files
from models.types import Backend, LossyAction
from pathing.resolver import validate_source_path
from ui.progress_view import ProgressView


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

    # 3. Resolve backend
    cli_backend: Backend | None = None
    if args.backend is not None:
        cli_backend = Backend(args.backend)

    backend_name = resolve_backend_for_run(cli_backend, settings)
    backend = get_backend(backend_name, settings)

    # 4. Validate source_path if given
    if args.source_path is not None:
        validate_source_path(args.input, args.source_path)

    # 5. Discover audio files
    files = discover_audio_files(args.input, args.exclude)

    if not files:
        print("No audio files found.")
        sys.exit(0)

    # Determine input_root and source_root for job building
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

    # 6. Build jobs
    lossy_action: LossyAction | None = None
    if args.lossy_action is not None:
        lossy_action = LossyAction(args.lossy_action)

    jobs, lossy_files_found = build_jobs(
        files=files,
        input_root=input_root,
        source_root=source_root,
        output_root=args.output,
        preset=preset,
        lossy_action=lossy_action,
        no_lossy_check=args.no_lossy_check,
        ffprobe_binary=settings.tools.ffprobe_binary,
        probe_workers=settings.execution.probe_workers,
    )

    # Lossy gate (step 6 of orchestration)
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

    # 7a. --list-lossy: print lossy files and exit
    if args.list_lossy:
        if not lossy_files_found:
            print("No lossy files found.")
        else:
            for f in lossy_files_found:
                print(f)
        sys.exit(0)

    # 7b. --dry-run: print job list and exit
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
        sys.exit(0)

    # 8. Real execution
    db_path = args.db if args.db is not None else Path(settings.history.db_path)
    db = ConversionDB(db_path)

    workers = args.workers if args.workers is not None else settings.execution.default_workers
    worker_model = args.worker_model if args.worker_model is not None else settings.execution.worker_model

    view = ProgressView(total=len(jobs), verbose=args.verbose)
    with view:
        summary = run_all(
            jobs=jobs,
            backend=backend,
            db=db,
            force=args.force,
            workers=workers,
            worker_model=worker_model,
            verbose=args.verbose,
            progress=view.progress,
            master_task=view.master_task,
        )

    # 9. Print final summary
    print()
    print(f"Done.  Success: {summary['success']}  Skipped: {summary['skipped']}  Failed: {summary['failed']}")


if __name__ == "__main__":
    _main()
