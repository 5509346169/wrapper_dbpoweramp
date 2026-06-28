"""cli/args.py: Command-line argument parsing and validation.

The argparse builder is split into per-group helper functions
(:func:`_add_required_args`, :func:`_add_backend_args`, etc.) so the
top-level :func:`parse_args` reads as a high-level outline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace


# ---------------------------------------------------------------------------
# Argument-group builders
# ---------------------------------------------------------------------------

def _add_required_args(parser: "ArgumentParser") -> None:
    """Add the three required positional-style flags: -I, -O, -p.

    These are NOT declared ``required=True`` at the argparse level: that
    would block ``--db-version`` and the ``db`` subcommand, neither of
    which need the conversion flags. ``validate_args`` enforces them
    after parsing.
    """
    parser.add_argument(
        "-I", "--input",
        type=Path,
        default=None,
        metavar="PATH",
        help="File or directory to convert",
    )
    parser.add_argument(
        "-O", "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output root directory",
    )
    parser.add_argument(
        "-p", "--preset",
        default=None,
        metavar="NAME",
        help="Preset name from presets.yaml (e.g. flac-lossless, mp3-320-cbr)",
    )


def _add_path_args(parser: "ArgumentParser") -> None:
    """Add --source-path, --exclude, --db, --force."""
    parser.add_argument(
        "--source-path",
        type=Path,
        metavar="PATH",
        help=(
            "Root used for relative-path math instead of --input; "
            "--input must be inside it"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        dest="exclude",
        metavar="DIR",
        help="Folder names to exclude from conversion (can be repeated)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        metavar="PATH",
        help="Override history database path from settings.yaml",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore resume history, reconvert everything",
    )


def _add_backend_args(parser: "ArgumentParser") -> None:
    """Add --backend and the mutually-exclusive --auto-detect-backend flags."""
    parser.add_argument(
        "--backend",
        choices=["wine_dbpoweramp", "native_dbpoweramp", "native_ffmpeg"],
        metavar="NAME",
        help="Override backend (default: from settings.yaml)",
    )
    backend_auto_group = parser.add_mutually_exclusive_group()
    backend_auto_group.add_argument(
        "--auto-detect-backend",
        action="store_true",
        dest="auto_detect_backend",
        default=None,
        help="Enable automatic backend detection (overrides --backend)",
    )
    backend_auto_group.add_argument(
        "--no-auto-detect-backend",
        action="store_false",
        dest="auto_detect_backend",
        default=None,
        help="Disable automatic backend detection",
    )


def _add_lossy_args(parser: "ArgumentParser") -> None:
    """Add --lossy-action and --no-lossy-check."""
    parser.add_argument(
        "--lossy-action",
        choices=["leave", "copy", "convert"],
        metavar="ACTION",
        help=(
            "What to do with lossy source files: "
            "leave (skip), copy (keep as-is), convert (transcode). "
            "Required if any lossy source files are found."
        ),
    )
    parser.add_argument(
        "--no-lossy-check",
        action="store_true",
        help="Disable lossy detection entirely (uses mutagen internally)",
    )


def _add_execution_args(parser: "ArgumentParser") -> None:
    """Add -w/--workers, --worker-model, --execution-mode, -v/--verbose, --verify-output, --verify-skip."""
    parser.add_argument(
        "-w", "--workers",
        type=int,
        metavar="N",
        help="Override execution.default_workers from settings.yaml",
    )
    parser.add_argument(
        "--worker-model",
        choices=["thread", "process"],
        metavar="MODEL",
        help="Override execution.worker_model from settings.yaml",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["hybrid", "phased"],
        default="hybrid",
        metavar="MODE",
        help="Execution mode: hybrid (interleave skip/copy/convert) or phased (skip → copy → convert sequentially)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Live verbose conversion stream",
    )
    parser.add_argument(
        "--verify-output",
        choices=["none", "full"],
        default="full",
        metavar="MODE",
        help=(
            "Post-conversion integrity check (default: full). "
            "'full' decodes every convert output frame-by-frame via "
            "libsndfile/miniaudio/mutagen; 'none' keeps the legacy "
            "existence+size check only."
        ),
    )
    parser.add_argument(
        "--verify-skip",
        action="store_true",
        help=(
            "Pre-verify skip candidates: before honouring a SUCCESS history "
            "row for a convert/copy job, re-decode the on-disk output via "
            "src.audio.integrity.verify_file. If the output is corrupt, the "
            "job is demoted from SKIP to CONVERT (so the pipeline re-runs it) "
            "and the original SUCCESS row is overwritten with the new result. "
            "Off by default — pre-verify adds a full-frame decode to every "
            "skip candidate, which can dominate runtime on large libraries."
        ),
    )
    parser.add_argument(
        "--db-version",
        action="store_true",
        dest="db_version",
        help="Print history DB schema version and exit.",
    )


def _add_mode_args(parser: "ArgumentParser") -> None:
    """Add --dry-run, --list-lossy, --build-index, --index, --no-scan-cache."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print the job list without converting anything",
    )
    parser.add_argument(
        "--list-lossy",
        action="store_true",
        help="Scan and print lossy files found, then exit",
    )
    parser.add_argument(
        "--build-index",
        type=Path,
        metavar="PATH",
        help="Build and save index database without converting, then exit",
    )
    parser.add_argument(
        "--index",
        type=Path,
        metavar="PATH",
        help="Use pre-built index database as input (skips filesystem scan/probe)",
    )
    parser.add_argument(
        "--no-scan-cache",
        action="store_true",
        dest="no_scan_cache",
        help=(
            "Disable the per-run scan cache (./tmp/scan_cache_*.db). "
            "By default the scan phase writes a small SQLite snapshot of "
            "the discovered files so the probe phase can skip the "
            "directory walk. Pass this flag to force a fresh walk every run."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> "Namespace":
    """Parse command-line arguments.

    Args:
        argv: Argument list to parse (defaults to sys.argv[1:]). For testing.

    Returns:
        An argparse.Namespace with all CLI flags as attributes.

    Note:
        ``-I/-O/-p`` are intentionally NOT marked ``required=True`` at the
        argparse level: that would block ``--db-version`` and the ``db``
        subcommand, neither of which need the conversion flags.
        ``validate_args`` enforces them after parsing.
    """
    parser = argparse.ArgumentParser(
        prog="wrapper-dbpoweramp",
        description="Audio format conversion wrapper using dBpoweramp or native ffmpeg.",
    )

    _add_required_args(parser)
    _add_path_args(parser)
    _add_backend_args(parser)
    _add_lossy_args(parser)
    _add_execution_args(parser)
    _add_mode_args(parser)

    # db subcommand group
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")
    db_parser = subparsers.add_parser("db", help="Inspect the conversion history database.")
    db_sub = db_parser.add_subparsers(dest="db_command", help="Database subcommands")

    def _add_db_path_arg(p: "ArgumentParser") -> None:
        """Add --db-path and --db to a db sub-subparser."""
        p.add_argument(
            "--db-path",
            type=Path,
            default=None,
            metavar="PATH",
            help="Path to history.db (default: settings.history.db_path).",
        )
        p.add_argument(
            "--db",
            type=Path,
            default=None,
            dest="db_path",
            metavar="PATH",
            help="Alias for --db-path.",
        )

    check_parser = db_sub.add_parser(
        "check",
        help="Print schema version, audit history, and exit.",
    )
    _add_db_path_arg(check_parser)

    migrate_parser = db_sub.add_parser(
        "migrate",
        help="Force-migrate the DB to the latest schema (auto-runs on first run anyway).",
    )
    _add_db_path_arg(migrate_parser)

    doctor_parser = db_sub.add_parser(
        "doctor",
        help="Like 'check', but also probes for orphaned .bak files and schema drift.",
    )
    _add_db_path_arg(doctor_parser)

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Cross-flag validation rules
# ---------------------------------------------------------------------------

def _fail(msg: str) -> None:
    """Print an error and exit with status 1."""
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def validate_args(args: "Namespace") -> None:
    """
    Validate cross-flag rules from 01-config-schema.md §3.

    Args:
        args: The parsed argparse.Namespace.

    Raises:
        SystemExit: If any validation rule is violated.
    """
    # Rule 1: --source-path must be ancestor of --input
    if args.source_path is not None:
        input_to_check: Path
        if args.input.is_file():
            input_to_check = args.input.parent
        else:
            input_to_check = args.input
        if not input_to_check.is_relative_to(args.source_path):
            _fail(
                f"--source-path {args.source_path} is not an ancestor of "
                f"--input {args.input}"
            )

    # Rule 2: --lossy-action and --no-lossy-check are contradictory
    if args.lossy_action is not None and args.no_lossy_check:
        _fail("--lossy-action and --no-lossy-check are mutually exclusive")

    # Rule 3: --dry-run and --list-lossy are mutually exclusive with --lossy-action
    # They are inspection-only modes that never need it (per spec §3 note 3).
    if (args.dry_run or args.list_lossy) and args.lossy_action is not None:
        mode = "--dry-run" if args.dry_run else "--list-lossy"
        _fail(
            f"{mode} is an inspection-only mode and does not use --lossy-action"
        )

    # Rule 4: --index and --build-index are mutually exclusive with each other
    if args.index is not None and args.build_index is not None:
        _fail("--index and --build-index are mutually exclusive")

    # Rule 5: --index and --build-index are mutually exclusive with --dry-run, --list-lossy
    if (args.index is not None or args.build_index is not None) and (
        args.dry_run or args.list_lossy
    ):
        mode = "--index" if args.index else "--build-index"
        inspection = "--dry-run" if args.dry_run else "--list-lossy"
        _fail(f"{mode} is incompatible with {inspection}")

    # Rule 6: --index requires an existing file
    if args.index is not None and not args.index.exists():
        _fail(f"--index file does not exist: {args.index}")

    # Rule 7: --build-index parent directory must exist and be writable
    if args.build_index is not None:
        parent = args.build_index.parent
        if not parent.exists():
            _fail(f"--build-index parent directory does not exist: {parent}")

    # --db-version and the `db` subcommand are self-contained: they do not
    # require the conversion flags (-I/-O/-p). Skip required-flag enforcement
    # when either is in effect so the dispatchers can return early.
    if getattr(args, "db_version", False):
        return
    if getattr(args, "command", None) == "db":
        return

    # Rule 8: -I, -O, -p are required for the conversion pipeline.
    missing: list[str] = []
    if getattr(args, "input", None) is None:
        missing.append("-I/--input")
    if getattr(args, "output", None) is None:
        missing.append("-O/--output")
    if getattr(args, "preset", None) is None:
        missing.append("-p/--preset")
    if missing:
        _fail(f"the following arguments are required: {', '.join(missing)}")
