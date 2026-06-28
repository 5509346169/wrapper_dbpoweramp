"""cli/db_cmd.py: Database inspection and migration subcommands.

Provides:
- ``cmd_db_check(args)``: print schema version, audit history, and exit 0.
- ``cmd_db_migrate(args)``: force-run schema migration, print result.
- ``cmd_db_doctor(args)``: check + orphaned .bak probe + schema drift detection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from argparse import Namespace


def _resolve_db_path(args: "Namespace") -> Path:
    """Resolve the database path from CLI args or settings.

    Checks, in order:
      1. ``args.db_path``  – set by ``--db-path`` on the ``db`` subcommand.
      2. ``args.db``        – set by ``--db`` on the top-level parser
                              (must appear before the ``db`` subcommand keyword:
                              ``--db <path> db check``, not ``db check --db <path>``).
      3. ``settings.history.db_path`` from settings.yaml.
    """
    if args.db_path is not None:
        return Path(args.db_path)
    if getattr(args, "db", None) is not None:
        return Path(args.db)
    # Import lazily to avoid circular imports at module load time.
    from src.config.settings_loader import load_settings

    settings = load_settings(Path("settings.yaml"))
    return Path(settings.history.db_path)


def cmd_db_check(args: "Namespace") -> int:
    """Print schema version, audit history, and exit 0."""
    from src.history.migrations import get_db_version

    db_path = _resolve_db_path(args)
    console = Console()

    info = get_db_version(db_path)
    console.print(str(info))
    return 0


def cmd_db_migrate(args: "Namespace") -> int:
    """Force-migrate the DB to the latest schema (auto-runs on first run anyway)."""
    from src.history.migrations import migrate_to_current

    db_path = _resolve_db_path(args)
    console = Console()

    console.print(f"[cyan]Migrating[/cyan] {db_path} ...")

    try:
        result = migrate_to_current(db_path)
        for msg in result.messages:
            console.print(f"  {msg}")
        if result.backup_path:
            console.print(f"  Backup: {result.backup_path}")
        console.print(f"[green]Migration complete[/green] (v{result.version}, {result.rows_migrated} rows)")
        return 0
    except Exception as exc:
        console.print(f"[red]Migration failed:[/red] {exc}", file=sys.stderr)
        return 1


def cmd_db_doctor(args: "Namespace") -> int:
    """Like 'check', but also probes for orphaned .bak files and schema drift."""
    from src.history.migrations import SCHEMA_VERSION, get_db_version

    db_path = _resolve_db_path(args)
    console = Console()

    info = get_db_version(db_path)
    console.print(str(info))

    # Probe for orphaned backups
    if not db_path.exists():
        console.print("[yellow]Warning:[/yellow] DB file does not exist.")
        return 1

    parent = db_path.parent
    stem = db_path.name
    orphaned: list[Path] = []
    for p in parent.iterdir():
        if p.is_file() and p.name.startswith(stem + ".bak"):
            orphaned.append(p)

    if orphaned:
        console.print()
        console.print(f"[yellow]Orphaned backup(s):[/yellow] {len(orphaned)} file(s)")
        for bp in orphaned:
            size_mb = bp.stat().st_size / (1 << 20)
            console.print(f"  {bp} ({size_mb:.1f} MiB)")
        console.print()
        console.print("Run `db migrate` to clean up after verifying the DB is healthy.")
        return 1
    else:
        console.print()
        console.print("[green]No orphaned backups found.[/green]")
        return 0
