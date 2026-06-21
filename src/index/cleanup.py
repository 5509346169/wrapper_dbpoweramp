"""
index/cleanup.py: Index database cleanup utilities.

NOTE: This module re-exports ``IndexError`` from ``exceptions``. That name shadows
Python's built-in ``builtins.IndexError`` within this module's scope. Any code
that needs the builtin (e.g. for list index out of range) must import it
explicitly: ``from builtins import IndexError as _BuiltinIndexError``.
"""

from pathlib import Path

from src.exceptions import IndexError


def cleanup_index(
    db_path: Path | None,
    failed_count: int,
    exception_info: str | None = None,
    interrupted: bool = False,
) -> None:
    if db_path is None or not db_path.exists():
        return

    should_keep = failed_count > 0 or exception_info is not None or interrupted

    if should_keep:
        print(f"[yellow]Index preserved:[/yellow] {db_path}")
        print(f"  Hint: sqlite3 {db_path} \"SELECT * FROM index_entries LIMIT 10;\"")
    else:
        try:
            db_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[yellow]Warning:[/yellow] failed to remove index file {db_path}: {e}")


# Re-export IndexError so callers can import it from here rather than from
# exceptions directly. This keeps all index-related public API in one package.
IndexError = IndexError  # type: ignore[assignment, misc]
