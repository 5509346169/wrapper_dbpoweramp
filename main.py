"""main.py — entry point. Dispatches to src/app/commands/* and exits."""

from __future__ import annotations

import sys
from pathlib import Path

from src.app.context import build_context
from src.app.commands import (
    build_index,
    db_check,
    db_migrate,
    dry_run,
    list_lossy,
    run_from_index,
    run_pipeline,
)
from src.cli.args import parse_args, validate_args


def main() -> int:
    args = parse_args()
    validate_args(args)

    # --db-version: print version block and exit (before any config load)
    if args.db_version:
        return db_check(args)

    # db subcommand group
    if args.command == "db":
        if args.db_command == "doctor":
            from src.cli.db_cmd import cmd_db_doctor

            return cmd_db_doctor(args)
        if args.db_command == "inspect":
            from src.cli.db_cmd import cmd_db_inspect

            return cmd_db_inspect(args)
        dispatch = {"check": db_check, "migrate": db_migrate}
        return dispatch[args.db_command](args)

    # Build context (loads settings + presets, resolves backend)
    ctx = build_context(args)

    # --build-index mode
    if args.build_index is not None:
        return build_index(ctx)

    # --index mode
    if args.index is not None:
        return run_from_index(ctx)

    # --dry-run / --list-lossy are inspection modes handled inside run_pipeline
    # (the pipeline functions check these flags internally)
    return run_pipeline(ctx)


def _main() -> int:
    """Legacy alias for backward compatibility with external scripts."""
    return main()


if __name__ == "__main__":
    sys.exit(main())
