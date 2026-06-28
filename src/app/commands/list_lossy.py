"""commands/list_lossy.py: --list-lossy command — scan and print lossy files found, then exit."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.context import AppContext


def run(ctx: "AppContext") -> int:
    """Print lossy files found and exit."""
    from src.app.pipeline.scan import scan

    scan_result = scan(ctx)

    lossy_files = [r.source_path for r in scan_result.rows if r.is_lossy]

    if not lossy_files:
        print("No lossy files found.")
    else:
        for f in lossy_files:
            print(f)

    return 0
