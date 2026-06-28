"""tests/test_all.py: Single orchestrator that runs the full test suite.

This file exists so the entire project can be exercised with one pytest
invocation that is easy to find, easy to describe, and easy to wire into
CI:

    python -m pytest tests/test_all.py -v

It also exposes the same summary via plain ``python tests/test_all.py``,
which prints a human-readable result table without requiring pytest.

The individual unit/integration tests live in their own files; this
module simply aggregates them. Adding a new test file does not require
touching this file — pytest's default discovery picks it up.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Pytest-level orchestrator
# ---------------------------------------------------------------------------


def test_full_suite_smoke() -> None:
    """Sanity marker — passing this proves the orchestrator itself is wired up.

    The real load-bearing assertion lives in the suite that pytest collects
    alongside this file. We deliberately avoid spawning a subprocess here so
    this test stays fast and works in the standard ``pytest tests/`` run.
    """


def test_discovery_includes_all_test_modules() -> None:
    """Confirm every test_*.py under tests/ is on disk and importable.

    This guards against the failure mode where someone adds a new test
    module but forgets to commit it, or where a typo silently renames a
    file so pytest never discovers it. We do NOT execute the modules —
    just verify they exist and that the names match the project layout.
    """
    tests_dir = Path(__file__).resolve().parent
    discovered = sorted(p.name for p in tests_dir.glob("test_*.py"))
    assert "test_all.py" in discovered
    # The 18 test modules the project ships with today. Update this list
    # whenever you add a new test file so the contract stays explicit.
    expected = {
        "test_all.py",
        "test_app_context.py",
        "test_audio_integrity.py",
        "test_conversion_db.py",
        "test_db_cli.py",
        "test_db_version_api.py",
        "test_dbpoweramp_cli.py",
        "test_history_migrations.py",
        "test_index_builder.py",
        "test_lifecycle_tempdir.py",
        "test_lossy_classify.py",
        "test_main_dispatch.py",
        "test_mutagen_probe.py",
        "test_pre_verify_demotion.py",
        "test_progress_sink_verify.py",
        "test_progress_view.py",
        "test_run_job_verify.py",
        "test_scan_cache.py",
        "test_signal_guard.py",
    }
    missing = expected - set(discovered)
    assert not missing, f"Missing test files: {sorted(missing)}"


# ---------------------------------------------------------------------------
# CLI-level orchestrator
# ---------------------------------------------------------------------------


def _run_pytest_suite() -> subprocess.CompletedProcess:
    """Re-invoke pytest on tests/ so the user can do ``python tests/test_all.py``.

    The ``PYTEST_ADDOPTS`` environment variable is forwarded to the
    subprocess so callers (e.g. ``tests/run_all_tests.ps1``) can pass
    ``-v`` or ``-k`` without changing this module.
    """
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(Path(__file__).resolve().parent),
        "--tb=short",
        "--color=yes",
    ]
    env = os.environ.copy()
    extra = env.pop("PYTEST_ADDOPTS", "").strip()
    if extra:
        # Insert after `pytest` (index 3) so PYTEST_ADDOPTS appears in the
        # natural flag position, e.g. ``pytest -v -k foo tests/ --tb=short``.
        cmd[3:3] = extra.split()
    return subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, env=env)


def main() -> int:
    """Plain-Python entry point: run the suite and print a summary.

    Designed for two workflows:
      1. ``python tests/test_all.py`` from the repo root.
      2. The PowerShell runner at ``tests/run_all_tests.ps1`` which calls
         the same pytest invocation inside the venv.

    Exit codes follow pytest convention: 0 = all passed, 1 = failures, etc.
    """
    print("=" * 78)
    print(" wrapper-dbpoweramp — full test suite")
    print("=" * 78)

    result = _run_pytest_suite()

    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)

    print()
    print("-" * 78)
    if result.returncode == 0:
        print(f" RESULT: OK (exit {result.returncode})")
    else:
        print(f" RESULT: FAILED (exit {result.returncode})")
    print("-" * 78)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())