"""tests/test_signal_guard.py: Tests for SignalGuard and install_signal_guard()."""

from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock

import pytest


class TestSignalGuard:
    """Tests for SignalGuard context manager."""

    def test_guard_restores_handlers(self):
        from src.app.lifecycle.signals import install_signal_guard

        original_sigint = signal.getsignal(signal.SIGINT)

        with install_signal_guard() as guard:
            # The guard captured the original sigint
            assert guard.old_sigint == original_sigint
            # The guard installed its own handler for the duration
            assert guard.old_sigint != signal.getsignal(signal.SIGINT)
            assert guard.interrupted is False

        # Handlers should be restored after the context
        assert signal.getsignal(signal.SIGINT) == original_sigint

    def test_guard_restores_on_exception(self):
        from src.app.lifecycle.signals import install_signal_guard

        original_sigint = signal.getsignal(signal.SIGINT)

        with pytest.raises(RuntimeError):
            with install_signal_guard() as guard:
                raise RuntimeError("test exception")

        # Handlers should still be restored
        assert signal.getsignal(signal.SIGINT) == original_sigint

    def test_guard_interrupted_flag_not_set_without_signal(self):
        from src.app.lifecycle.signals import install_signal_guard

        with install_signal_guard() as guard:
            assert guard.interrupted is False

    def test_guard_restores_on_nested_context(self):
        from src.app.lifecycle.signals import install_signal_guard

        original = signal.getsignal(signal.SIGINT)

        with install_signal_guard() as outer:
            outer_handler = signal.getsignal(signal.SIGINT)
            with install_signal_guard() as inner:
                inner_handler = signal.getsignal(signal.SIGINT)
                # Both should be different from original
                assert inner_handler != original
                assert outer_handler != original

            # After inner exits, outer handler should be active
            assert signal.getsignal(signal.SIGINT) == outer_handler

        # After outer exits, original should be restored
        assert signal.getsignal(signal.SIGINT) == original


class TestSignalGuardRestore:
    """Tests for SignalGuard.restore()."""

    def test_restore_sets_original_handlers(self):
        from src.app.lifecycle.signals import SignalGuard

        # Directly verify restore() calls signal.signal with the stored handlers.
        # We mock signal.signal to avoid depending on the global handler state
        # (pytest may have installed its own SIG_IGN handler).
        mock_old_int = object()
        mock_old_term = object()

        guard = SignalGuard(old_sigint=mock_old_int, old_sigterm=mock_old_term)

        import unittest.mock as mock
        with mock.patch("signal.signal") as patched_signal:
            guard.restore()
            # restore() calls signal.signal for both SIGINT and SIGTERM
            calls = patched_signal.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] == signal.SIGINT
            assert calls[0][0][1] is mock_old_int
            assert calls[1][0][0] == signal.SIGTERM
            assert calls[1][0][1] is mock_old_term
