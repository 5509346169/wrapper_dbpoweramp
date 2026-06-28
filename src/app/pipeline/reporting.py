"""app/pipeline/reporting.py: Final summary and formatting utilities."""

from __future__ import annotations


def format_bytes(num_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if num_bytes >= 1 << 30:
        return f"{num_bytes / (1 << 30):.1f} GiB"
    if num_bytes >= 1 << 20:
        return f"{num_bytes / (1 << 20):.1f} MiB"
    if num_bytes >= 1 << 10:
        return f"{num_bytes / (1 << 10):.1f} KiB"
    return f"{num_bytes} B"


def print_summary(summary: dict[str, int]) -> None:
    """Print the final 'Done.' summary line."""
    print()
    print(
        f"Done.  Success: {summary['success']}  "
        f"Skipped: {summary['skipped']}  Failed: {summary['failed']}"
    )
