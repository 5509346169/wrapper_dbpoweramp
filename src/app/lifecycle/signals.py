"""app/lifecycle/signals.py: Signal handler lifecycle — SignalGuard context manager."""

from __future__ import annotations

import signal
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from rich import print as rprint


@dataclass
class SignalGuard:
    """Holds the installed signal handlers and tracks interrupt state."""

    old_sigint: Callable[[int, object], None]
    old_sigterm: Callable[[int, object], None]
    interrupted: bool = False

    def restore(self) -> None:
        """Restore the original signal handlers."""
        signal.signal(signal.SIGINT, self.old_sigint)
        signal.signal(signal.SIGTERM, self.old_sigterm)


@contextmanager
def install_signal_guard() -> Iterator[SignalGuard]:
    """Install SIGINT/SIGTERM handlers, yield a guard, and restore originals on exit.

    The guard's ``.interrupted`` flag is set to True by the handlers.

    Usage::

        with install_signal_guard() as guard:
            ...  # run work
        # handlers are restored here

    Raises:
        SystemExit: If SIGINT/SIGTERM is caught while inside the context.
    """
    interrupted = False

    def _handler(signum, frame):  # noqa: ANN001
        nonlocal interrupted
        interrupted = True
        rprint("\n[yellow]Interrupted.[/yellow]", file=__import__('sys').stderr)

    old_sigint = signal.signal(signal.SIGINT, _handler)
    old_sigterm = signal.signal(signal.SIGTERM, _handler)

    guard = SignalGuard(old_sigint=old_sigint, old_sigterm=old_sigterm, interrupted=interrupted)

    try:
        yield guard
    finally:
        guard.restore()
