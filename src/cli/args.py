"""cli/args.py: Command-line argument parsing and validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace


def parse_args(argv: list[str] | None = None) -> "Namespace":
    """
    Parse command-line arguments.

    Args:
        argv: Argument list to parse (defaults to sys.argv[1:]). For testing.

    Returns:
        An argparse.Namespace with all CLI flags as attributes.
    """
    parser = argparse.ArgumentParser(
        prog="wrapper-dbpoweramp",
        description="Audio format conversion wrapper using dBpoweramp or native ffmpeg.",
    )

    # Required
    parser.add_argument(
        "-I", "--input",
        required=True,
        type=Path,
        metavar="PATH",
        help="File or directory to convert",
    )
    parser.add_argument(
        "-O", "--output",
        required=True,
        type=Path,
        metavar="PATH",
        help="Output root directory",
    )
    parser.add_argument(
        "-p", "--preset",
        required=True,
        metavar="NAME",
        help="Preset name from presets.yaml (e.g. flac-lossless, mp3-320-cbr)",
    )

    # Optional
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
        "-v", "--verbose",
        action="store_true",
        help="Live verbose conversion stream",
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

    return parser.parse_args(argv)


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
            print(
                f"error: --source-path {args.source_path} is not an ancestor of "
                f"--input {args.input}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Rule 2: --lossy-action and --no-lossy-check are contradictory
    if args.lossy_action is not None and args.no_lossy_check:
        print(
            "error: --lossy-action and --no-lossy-check are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rule 3: --dry-run and --list-lossy are mutually exclusive with --lossy-action
    # They are inspection-only modes that never need it (per spec §3 note 3).
    if (args.dry_run or args.list_lossy) and args.lossy_action is not None:
        mode = "--dry-run" if args.dry_run else "--list-lossy"
        print(
            f"error: {mode} is an inspection-only mode and does not use --lossy-action",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rule 4: --index and --build-index are mutually exclusive with each other
    if args.index is not None and args.build_index is not None:
        print(
            "error: --index and --build-index are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rule 5: --index and --build-index are mutually exclusive with --dry-run, --list-lossy
    if (args.index is not None or args.build_index is not None) and (
        args.dry_run or args.list_lossy
    ):
        mode = "--index" if args.index else "--build-index"
        inspection = "--dry-run" if args.dry_run else "--list-lossy"
        print(
            f"error: {mode} is incompatible with {inspection}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rule 6: --index requires an existing file
    if args.index is not None and not args.index.exists():
        print(
            f"error: --index file does not exist: {args.index}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Rule 7: --build-index parent directory must exist and be writable
    if args.build_index is not None:
        parent = args.build_index.parent
        if not parent.exists():
            print(
                f"error: --build-index parent directory does not exist: {parent}",
                file=sys.stderr,
            )
            sys.exit(1)
