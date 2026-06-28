"""commands/db_check.py: Thin wrapper re-exporting from src.cli.db_cmd."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace


def run(args: "Namespace") -> int:
    """Print schema version, audit history, and exit 0."""
    from src.cli.db_cmd import cmd_db_check

    return cmd_db_check(args)
