"""timed_wrapper.py: Run a command, enforce optional timeout, report elapsed time."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from threading import Event, Thread, Timer


try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


def _log(msg: str):
    """Print wrapper metadata to stderr so it never mixes with subprocess output."""
    print(msg, flush=True)


def _keyboard_monitor(kill_event: Event, stop_event: Event, proc_ref, start_ref):
    """Background thread: poll for 'k' keypress to kill the subprocess."""
    while not kill_event.wait(timeout=0.2):
        try:
            if _HAS_MSVCRT and msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'k', b'K'):
                    proc = proc_ref()
                    start = start_ref()
                    elapsed = time.monotonic() - start
                    _log(f"\n[KEY 'k' PRESSED]  [ELAPSED] {elapsed:.2f}s")
                    if proc and proc.poll() is None:
                        _log(f"[TERMINATING] PID {proc.pid} ...")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            _log(f"[KILLING] PID {proc.pid} ...")
                            proc.kill()
                            proc.wait()
                    stop_event.set()
                    break
        except Exception:
            pass


def run_timed(command: list[str], timeout: int | None = None) -> int:
    """
    Run ``command`` with optional timeout. The subprocess output goes directly
    to the terminal (no piping), so Rich progress bars and Unicode characters
    render correctly. Wrapper metadata is printed to stderr.

    Press 'k' to kill the process early (Windows: immediate; Unix: next poll).

    Args:
        command: Command and arguments as a list of strings.
        timeout: Optional timeout in seconds.

    Returns:
        Exit code from the subprocess.
    """
    proc_env = os.environ.copy()
    proc_env["PYTHONIOENCODING"] = "utf-8"

    _log(f"[CMD] {' '.join(command)}")
    _log(f"[START] {time.strftime('%H:%M:%S')}")
    if timeout is not None:
        _log(f"[TIMEOUT] {timeout}s")
    if _HAS_MSVCRT:
        _log("[INTERACTIVE] Press 'k' to kill the process  |  Ctrl+C to interrupt")

    start = time.monotonic()
    proc: subprocess.Popen | None = None
    timed_out = False

    proc_ref = lambda: proc
    start_ref = lambda: start
    kill_event = Event()
    stop_event = Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal.SIG_DFL)

    monitor = Thread(target=_keyboard_monitor, args=(kill_event, stop_event, proc_ref, start_ref), daemon=True)
    monitor.start()

    timer: Timer | None = None

    def timeout_handler():
        nonlocal timed_out, proc
        elapsed = time.monotonic() - start
        _log(f"\n[TIMEOUT after {timeout}s]  [ELAPSED] {elapsed:.2f}s")
        if proc and proc.poll() is None:
            timed_out = True
            _log(f"[TERMINATING] PID {proc.pid} ...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _log(f"[KILLING] PID {proc.pid} ...")
                proc.kill()
                proc.wait()
        stop_event.set()

    if timeout is not None:
        timer = Timer(timeout, timeout_handler)
        timer.daemon = True
        timer.start()

    try:
        # No stdout/stderr piping — output goes straight to terminal.
        # stdin=/dev/null so the subprocess never reads wrapper keyboard input.
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            env=proc_env,
        )

        # Poll every 0.5s so stop_event can interrupt the wait.
        while True:
            ret = proc.poll()
            if ret is not None:
                exit_code = ret
                break
            if stop_event.wait(timeout=0.5):
                exit_code = proc.wait()
                break

        elapsed = time.monotonic() - start
        kill_event.set()
        monitor.join(timeout=1)

        _log(f"\n[EXIT] {exit_code}")
        _log(f"[ELAPSED] {elapsed:.2f}s")
        if timed_out:
            _log("[KILLED] True")
        return exit_code

    except KeyboardInterrupt:
        elapsed = time.monotonic() - start
        _log(f"\n[INTERRUPTED]  [ELAPSED] {elapsed:.2f}s")
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
        return -1

    finally:
        kill_event.set()
        if timer is not None:
            timer.cancel()


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

    timeout: int | None = None
    if command and command[0] == "--timeout":
        timeout = int(command[1])
        command = command[2:]

    if timeout is None:
        env_timeout = os.environ.get("WRAPPER_TIMEOUT")
        timeout = int(env_timeout) if env_timeout else None

    sys.exit(run_timed(command, timeout))
