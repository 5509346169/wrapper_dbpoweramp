"""app/context.py: AppContext — frozen bundle of everything resolved once at startup."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace
    from src.backends.base import ConversionBackend
    from src.config.models import PresetConfig, Settings
    from src.models.types import Backend, ConversionJob, ExecutionMode, WorkerModel


@dataclass(frozen=True)
class AppContext:
    """Frozen bundle of everything resolved once in main() and passed to commands."""

    args: "Namespace"
    settings: "Settings"
    preset: "PresetConfig"
    backend: "ConversionBackend"
    backend_name: "Backend"
    db_path: Path
    workers: int
    worker_model: "WorkerModel"
    execution_mode: "ExecutionMode"
    verbose: bool
    long_paths: bool = False
    # When True, the prefilter restricts pending jobs to those whose latest
    # history row is FAILED, and ``run_job`` re-encodes them instead of
    # short-circuiting via ``last_failure()``. Default False.
    failed_only: bool = False


@dataclass
class MutablePhaseState:
    """Mutable result lists populated during the pipeline, passed by reference."""

    prefilter_skips: list["ConversionJob"] = field(default_factory=list)
    pending_jobs: list["ConversionJob"] = field(default_factory=list)
    skipped_jobs: list["ConversionJob"] = field(default_factory=list)


def build_context(args: "Namespace") -> AppContext:
    """Build an AppContext from the parsed CLI args.

    Loads settings, resolves the backend, checks preset compatibility,
    and assembles everything into a frozen dataclass.

    Args:
        args: Parsed argparse.Namespace from parse_args().

    Returns:
        A fully-populated AppContext.

    Raises:
        SystemExit: If preset resolution, backend loading, or preset compatibility fails.
    """
    from src.app.backend import resolve_backend_name, supports
    from src.backends.registry import get_backend
    from src.config.preset_loader import get_preset, load_presets
    from src.config.settings_loader import load_settings
    from src.exceptions import BackendError, PresetNotFoundError
    from src.models.types import ExecutionMode

    # 1. Load config + presets
    settings = load_settings(Path("settings.yaml"))
    presets = load_presets(Path("settings.yaml").parent / "presets.yaml")

    try:
        preset = get_preset(presets, args.preset)
    except PresetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Resolve backend
    backend_name = resolve_backend_name(args, settings, preset)
    try:
        backend = get_backend(backend_name, settings)
    except BackendError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 3. Preset compatibility gate
    if not supports(backend, preset):
        print(
            f"error: backend '{backend_name.value}' does not support preset '{preset.name}'.\n"
            f"  Choose a different backend with --backend, or pick a preset that supports "
            f"'{backend_name.value}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 4. Resolve runtime parameters
    db_path = args.db if args.db is not None else Path(settings.history.db_path)
    workers = args.workers if args.workers is not None else settings.execution.default_workers
    worker_model = args.worker_model if args.worker_model is not None else settings.execution.worker_model
    execution_mode = ExecutionMode(
        getattr(args, "execution_mode", None) or settings.execution.execution_mode
    )
    verbose = args.verbose

    # Long-path workaround: CLI flag overrides settings.yaml. Only meaningful
    # for the native dBpoweramp backend; we still pass the value through to
    # the context so the backend can read it from a single source of truth.
    cli_long_paths = getattr(args, "long_paths", None)
    long_paths = (
        cli_long_paths
        if cli_long_paths is not None
        else settings.backend.native_dbpoweramp.long_paths
    )

    # --failed-only is a CLI-only flag (no settings.yaml default — it is a
    # per-run retry instruction, not a behavioural preference). argparse
    # leaves ``failed_only`` as ``None`` when the user passed neither flag,
    # so we collapse that to ``False`` here.
    failed_only = bool(getattr(args, "failed_only", False))

    return AppContext(
        args=args,
        settings=settings,
        preset=preset,
        backend=backend,
        backend_name=backend_name,
        db_path=db_path,
        workers=workers,
        worker_model=worker_model,
        execution_mode=execution_mode,
        verbose=verbose,
        long_paths=long_paths,
        failed_only=failed_only,
    )
