"""app/lifecycle/tempdir.py: Temp directory and index DB lifecycle management."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from rich import print as rprint


def setup_temp_dir() -> tuple[Path, Path | None]:
    """Create ./tmp/, ./tmp/audio/src/, ./tmp/audio/dst/, and return
    ``(tmp_dir, index_db_path)``.

    The ``tmp/audio/src/`` and ``tmp/audio/dst/`` subdirectories are used by
    the native dBpoweramp backend's long-path workaround (see
    :mod:`src.pathing.long_path`): each conversion copies its source to a
    short path under ``tmp/audio/src/`` and lets CoreConverter write its
    output to ``tmp/audio/dst/`` so neither the wrapper nor the encoder
    ever sees a path that exceeds Windows MAX_PATH (260 chars).

    Returns ``(tmp_dir, None)`` if the directory cannot be created.
    """
    tmp_dir = Path("tmp")
    try:
        tmp_dir.mkdir(exist_ok=True)
        # Pre-create the audio staging tree so stage_paths() never has to
        # mkdir inside the worker hot path (mkdir costs a syscall per job
        # if every job has to do it; doing it once here keeps the per-job
        # overhead to one shutil.copy2).
        for sub in ("src", "dst"):
            (tmp_dir / "audio" / sub).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"warning: could not create {tmp_dir} for index DB: {exc}", file=__import__('sys').stderr)
        return tmp_dir, None
    index_db_path: Path | None = tmp_dir / "index.db"
    return tmp_dir, index_db_path


def cleanup_staging_workspace() -> None:
    """Clear every file under ``tmp/audio/src/`` and ``tmp/audio/dst/``.

    Called at the *start* of every pipeline run so leftover files from a
    previous interrupted or crashed run don't accumulate across runs. We
    don't do this at the end-of-run cleanup because the per-job
    ``unstage()`` already removes the staged files for successful jobs;
    the only files left over are those from failed/interrupted jobs,
    which is exactly what we want to clear at the next run's start.

    Errors are swallowed — a leftover file is harmless (it just gets
    overwritten the next time the same hash is generated, and deleted on
    the next run's startup cleanup).
    """
    audio = Path("tmp") / "audio"
    if not audio.exists():
        return
    for sub in ("src", "dst"):
        d = audio / sub
        if not d.exists():
            continue
        for entry in d.iterdir():
            try:
                if entry.is_file() or entry.is_symlink():
                    entry.unlink()
                elif entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass


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
