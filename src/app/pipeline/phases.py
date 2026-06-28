"""app/pipeline/phases.py: Job phase splitting — hybrid vs phased execution modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.types import ConversionJob

if TYPE_CHECKING:
    from src.app.context import AppContext


def run_jobs_by_phase(
    jobs: list[ConversionJob],
    ctx: "AppContext",
) -> list[tuple[str, list[ConversionJob]]]:
    """Split jobs into sequential phases according to execution_mode.

    In 'hybrid' mode returns a single batch containing all jobs.
    In 'phased' mode returns three batches in strict order: skip → copy → convert.
    Empty job-type lists are omitted from the result.

    Args:
        jobs: The pending jobs to split.
        ctx: The application context.

    Returns:
        A list of (phase_label, batch) tuples.
    """
    if ctx.execution_mode.value == "hybrid":
        return [("convert", jobs)]

    phased: list[tuple[str, list[ConversionJob]]] = []
    for jtype, label in [
        ("skip", "Skipping"),
        ("copy", "Copying"),
        ("convert", "Converting"),
    ]:
        batch = [j for j in jobs if j.job_type == jtype]
        if batch:
            phased.append((label, batch))
    return phased
