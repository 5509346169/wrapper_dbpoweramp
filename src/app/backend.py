"""app/backend.py: Backend resolution helpers pulled from main.py.

Provides ``resolve_backend_name()`` and ``supports()`` as a reusable surface.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace
    from src.backends.base import ConversionBackend
    from src.config.models import PresetConfig, Settings
    from src.models.types import Backend


def resolve_backend_name(
    args: "Namespace",
    settings: "Settings",
    preset: "PresetConfig",
) -> "Backend":
    """Pick the backend for this run, honouring the CLI override and the auto-detect toggle."""
    from src.backends.registry import detect_backend_for_run
    from src.models.types import Backend

    cli_backend: "Backend | None" = None
    if args.backend is not None:
        cli_backend = Backend(args.backend)

    return detect_backend_for_run(
        cli_backend=cli_backend,
        settings=settings,
        preset=preset,
        platform=sys.platform,
        auto_detect_override=args.auto_detect_backend,
    )


def supports(backend: "ConversionBackend", preset: "PresetConfig") -> bool:
    """Return True if the backend can encode to the preset's output format."""
    return backend.supports(preset)
