"""timed_wrapper.py: Run a command, enforce optional timeout, report elapsed time."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _make_signal_handler(proc: subprocess.Popen | None, start: float):
    def handler(signum, frame):
        elapsed = time.monotonic() - start
        sig_name = signal.Signals(signum).name
        print(f"\n[SIGNAL {sig_name}]  [ELAPSED] {elapsed:.2f}s", flush=True)
        if proc and proc.poll() is None:
            print(f"[TERMINATING] PID {proc.pid} ...", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[KILLING] PID {proc.pid} ...", flush=True)
                proc.kill()
                proc.wait()
        sys.exit(128 + signum)
    return handler


def run_timed(command: list[str], timeout: int | None = None) -> int:
    """
    Run ``command`` with optional timeout, streaming stdout+stderr in real-time.

    Reports elapsed time on natural exit, timeout, or signal kill.

    Args:
        command: Command and arguments as a list of strings.
        timeout: Optional timeout in seconds. Process receives SIGTERM (then SIGKILL).

    Returns:
        Exit code from the subprocess (128+signal on signal death, -1 on KeyboardInterrupt).
    """
    print(f"[CMD] {' '.join(command)}", flush=True)
    print(f"[START] {time.strftime('%H:%M:%S')}", flush=True)
    if timeout is not None:
        print(f"[TIMEOUT] {timeout}s", flush=True)

    start = time.monotonic()
    old_handlers: dict[int, signal.Handler] = {}

    proc: subprocess.Popen | None = None
    timed_out = False

    # Install signal handlers so Ctrl+C / SIGTERM propagate correctly.
    for sig in (signal.SIGINT, signal.SIGTERM):
        old_handlers[sig] = signal.signal(sig, signal.SIG_DFL)

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if timeout is not None:
            def timeout_handler():
                nonlocal timed_out, proc
                elapsed = time.monotonic() - start
                print(f"\n[TIMEOUT after {timeout}s]  [ELAPSED] {elapsed:.2f}s", flush=True)
                if proc and proc.poll() is None:
                    timed_out = True
                    print(f"[TERMINATING] PID {proc.pid} ...", flush=True)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print(f"[KILLING] PID {proc.pid} ...", flush=True)
                        proc.kill()
                        proc.wait()

            timer = signal.ITIMER_REAL
            signal.setitimer(timer, timeout, 0.0)
            old_sigalrm = signal.signal(signal.SIGALRM, lambda s, f: timeout_handler())

        # Stream output in real-time.
        if proc.stdout:
            for line in proc.stdout:
                print(line, end="", flush=True)

        exit_code = proc.wait()
        elapsed = time.monotonic() - start

        print(f"[EXIT] {exit_code}", flush=True)
        print(f"[ELAPSED] {elapsed:.2f}s", flush=True)
        if timed_out:
            print("[KILLED] True", flush=True)
        return exit_code

    except KeyboardInterrupt:
        # Should not reach here — SIG_DFL handles it, but keep as fallback.
        elapsed = time.monotonic() - start
        print(f"\n[INTERRUPTED]  [ELAPSED] {elapsed:.2f}s", flush=True)
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
        return -1

    finally:
        # Restore old signal handlers.
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if timeout is not None:
            signal.setitimer(signal.ITIMER_REAL, 0, 0.0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python timed_wrapper.py <command> [args...]")
        print("       python timed_wrapper.py --timeout 30 <command> [args...]")
        print("       WRAPPER_TIMEOUT=30 python timed_wrapper.py <command>")
        print()
        print("Examples:")
        print("  python timed_wrapper.py python script.py")
        print("  python timed_wrapper.py --timeout 60 python long_running.py")
        print("  WRAPPER_TIMEOUT=120 python timed_wrapper.py python script.py --arg1 val1")
        sys.exit(1)

    command = sys.argv[1:]

    # Parse --timeout N from command line.
    timeout: int | None = None
    if command and command[0] == "--timeout":
        timeout = int(command[1])
        command = command[2:]

    if timeout is None:
        env_timeout = os.environ.get("WRAPPER_TIMEOUT")
        timeout = int(env_timeout) if env_timeout else None

    sys.exit(run_timed(command, timeout))
