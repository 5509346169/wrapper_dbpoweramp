"""commands/db_migrate.py: Thin wrapper re-exporting from src.cli.db_cmd."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace


def run(args: "Namespace") -> int:
    """Force-migrate the DB to the latest schema."""
    from src.cli.db_cmd import cmd_db_migrate

    return cmd_db_migrate(args)
