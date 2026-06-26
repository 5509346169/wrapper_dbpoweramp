"""jobs/classify.py: Decide job_type for a row and apply it to the IndexRow in place.

The classify helper is the only place where lossy-status → job_type mapping
lives. Both the streaming and blocking enrich paths call it so the
behaviour stays consistent.
"""

from pathlib import Path

from src.index.scanner import IndexRow
from src.models.types import LossyAction, PresetConfig
from src.pathing.resolver import compute_output_path


def decide_job_type(
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
) -> str:
    """Pure helper: pick job_type based on lossy status and configured action."""
    if no_lossy_check:
        return "convert"
    if is_lossy_val:
        if lossy_action is None:
            return "skip"
        if lossy_action == LossyAction.LEAVE:
            return "skip"
        if lossy_action == LossyAction.COPY:
            return "copy"
        return "convert"
    return "convert"


def classify(
    row: IndexRow,
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
) -> None:
    """Classify a single row and write it to the index DB immediately.

    Note: mutates ``row`` in-place via ``object.__setattr__`` (IndexRow is frozen).
    """
    f = Path(row.source_path)
    job_type = decide_job_type(is_lossy_val, lossy_action, no_lossy_check)

    object.__setattr__(row, "is_lossy", is_lossy_val)
    object.__setattr__(row, "job_type", job_type)

    outfile = compute_output_path(
        f,
        input_root,
        source_root,
        output_root,
        preset.ext,
    )
    object.__setattr__(row, "dest_path", str(outfile))
