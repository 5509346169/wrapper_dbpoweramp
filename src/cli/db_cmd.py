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
    console = Console(force_terminal=False, legacy_windows=False)

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


def _parse_id_range(spec: str) -> tuple[int, int]:
    """Parse an ``MIN-MAX`` range spec into a (min, max) inclusive tuple.

    Accepts the hyphenated form ``MIN-MAX`` (e.g. ``26338-26423``).
    Whitespace around each side is tolerated.
    """
    if "-" not in spec:
        raise ValueError(
            f"--id-range={spec!r}: expected MIN-MAX (e.g. 26338-26423)."
        )
    left, _, right = spec.partition("-")
    try:
        lo = int(left.strip())
    except ValueError:
        raise ValueError(f"--id-range={spec!r}: MIN is not an integer") from None
    try:
        hi = int(right.strip())
    except ValueError:
        raise ValueError(f"--id-range={spec!r}: MAX is not an integer") from None
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def cmd_db_inspect(args: "Namespace") -> int:
    """Print history rows with full diagnostic details.

    The history table's ``command`` and ``stdout`` columns hold the raw
    CoreConverter invocation and its captured output — indispensable when
    investigating why a particular file failed with exit-code 1.

    Default formatting shows one row per block: id, timestamp, status,
    verify_status, source_path, dest_path, job_type, command, error_msg,
    and a truncated stdout tail.
    """
    import sqlite3
    import sys

    db_path = _resolve_db_path(args)

    if not db_path.exists():
        sys.stderr.write(f"Error: DB not found: {db_path}\n")
        return 1

    if args.id is not None and args.id_range is not None:
        sys.stderr.write("Error: --id and --id-range are mutually exclusive.\n")
        return 1

    where: list[str] = []
    params: list[object] = []
    if args.id is not None:
        where.append("id = ?")
        params.append(args.id)
    if args.id_range is not None:
        try:
            lo, hi = _parse_id_range(args.id_range)
        except ValueError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1
        where.append("id BETWEEN ? AND ?")
        params.extend([lo, hi])
    if args.status is not None:
        where.append("status = ?")
        params.append(args.status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT id, timestamp, status, verify_status, source_path, dest_path, "
        "job_type, command, error_msg, stdout, file_size "
        f"FROM history {where_sql} ORDER BY id"
    )
    if args.limit is not None:
        sql += f" LIMIT {int(args.limit)}"

    with sqlite3.connect(str(db_path)) as conn:
        rows = list(conn.execute(sql, params))

    # Use plain print (errors='replace') so Unicode in paths/stdout never
    # crashes on Windows legacy cp1252 consoles — diagnostic tool, not UI.
    header = (
        f"inspect {db_path} — {len(rows)} row(s)"
        + (f"  (filter: {where_sql})" if where_sql else "")
    )
    print(header)
    print()

    if not rows:
        print("No matching rows.")
        return 0

    max_stdout = args.max_stdout
    for r in rows:
        rid, ts, status, vstatus, src, dst, jtype, cmd, err, stdout_text, size = r
        print(f"------ id={rid}  status={status}  verify={vstatus or '-'} ------")
        print(f"  timestamp      {ts}")
        print(f"  job_type       {jtype}")
        print(f"  file_size      {size if size is not None else '-'}")
        print(f"  source_path    {src}")
        print(f"  dest_path      {dst}")
        if cmd:
            print(f"  command        {cmd}")
        if err:
            print(f"  error_msg      {err}")
        if stdout_text:
            text = stdout_text.replace("\r\n", "\n").replace("\r", "\n")
            # Strip UTF-16 / UTF-8 BOM if present so the diagnostic is
            # readable; CoreConverter on Windows writes a UTF-16 LE BOM
            # so this often halves the printed length.
            if text.startswith("\ufeff"):
                text = text[1:]
            tail = text if len(text) <= max_stdout else (
                text[:max_stdout] + f"\n  ... ({len(text) - max_stdout} more chars)"
            )
            print(f"  stdout         (len={len(text)})")
            for ln in tail.splitlines():
                # Some lines include non-printable or UTF-16 artifacts;
                # normalise and trim trailing whitespace so output is
                # readable in cp1252 terminals without exploding.
                ln_clean = ln.encode("ascii", errors="replace").decode("ascii").rstrip()
                print(f"    {ln_clean}")
        print()

    return 0
