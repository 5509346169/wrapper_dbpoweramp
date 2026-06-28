"""app/lifecycle/tempdir.py: Temp directory and index DB lifecycle management."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich import print as rprint


def setup_temp_dir() -> tuple[Path, Path | None]:
    """Create ./tmp/ and return (tmp_dir, index_db_path).

    Returns (tmp_dir, None) if the directory cannot be created.
    """
    tmp_dir = Path("tmp")
    try:
        tmp_dir.mkdir(exist_ok=True)
    except OSError as exc:
        print(f"warning: could not create {tmp_dir} for index DB: {exc}", file=__import__('sys').stderr)
        return tmp_dir, None
    index_db_path: Path | None = tmp_dir / "index.db"
    return tmp_dir, index_db_path


def cleanup_index(
    db_path: Path | None,
    failed_count: int,
    exception_info: str | None = None,
    interrupted: bool = False,
) -> None:
    """Decide whether to keep or delete the temp index DB.

    - Keeps on failure, exception, or interrupt.
    - Deletes on clean success.
    """
    if db_path is None or not db_path.exists():
        return

    should_keep = failed_count > 0 or exception_info is not None or interrupted

    if should_keep:
        rprint(f"[yellow]Index preserved:[/yellow] {db_path}")
        print(f"  Hint: sqlite3 {db_path} \"SELECT * FROM index_entries LIMIT 10;\"")
    else:
        try:
            db_path.unlink(missing_ok=True)
        except OSError as e:
            print(f"[yellow]Warning:[/yellow] failed to remove index file {db_path}: {e}")
