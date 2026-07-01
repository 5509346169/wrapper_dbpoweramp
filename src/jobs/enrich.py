"""jobs/enrich.py: Stream-probe and block-probe audio files for lossy classification.

Two entry points:

* :func:`enrich_index_rows` — blocking convenience wrapper that runs the full
  cascade against a list of ``IndexRow`` objects and returns the lossy
  subset.
* :func:`enrich_index_rows_streaming` — same cascade but with live progress
  reporting and incremental writes to an ``IndexBuilder`` as each row
  resolves.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from src.audio.inspector import (
    CascadeTier,
    cascade_with_tier,
    probe_many,
)
from src.index.builder import IndexBuilder
from src.index.scanner import IndexRow
from src.models.types import LossyAction, PresetConfig
from src.pathing.resolver import compute_output_path

from src.jobs.classify import classify, decide_job_type

if TYPE_CHECKING:
    from src.ui.progress_view import ProgressSink


def enrich_index_rows_streaming(
    scan_rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
    progress: "ProgressSink",
    index_builder: IndexBuilder | None,
) -> list[Path]:
    """Stream-probe files, write rows to the index DB incrementally, and report live progress.

    Detection cascade runs **per file** inside each worker thread:
      1. Extension — Tier 1 resolves immediately for unambiguous extensions.
      2. Folder    — Tier 2 resolves by parent-directory name if Tier 1 was unknown.
      3. Mutagen   — Tier 3 (the only filesystem-bound tier) is the fallback.

    Each file walks the cascade independently in parallel. The progress
    bar stays as a single "Probing" bar, and its phase label flips
    (Extension -> Folder -> Mutagen) based on which tier resolved the
    most recent file — this lets the user see *what* the workers are
    currently doing without fragmenting the display into three bars.

    Args:
        scan_rows:     Rows from the scanner (source_path, file_size, sidecar_files, mtime set).
        progress:      A ``ProgressSink`` whose ``advance()`` is called after each result.
        index_builder: If provided, each completed row is written to the DB immediately.
        (all other args are identical to ``enrich_index_rows`` — see that docstring).

    Returns:
        List of source paths that are lossy (for the lossy-action gate).
    """
    path_to_row: dict[Path, IndexRow] = {Path(r.source_path): r for r in scan_rows}
    files = list(path_to_row.keys())
    total = len(files)

    lossy_files_found: list[Path] = []
    # Tier counters are racy across worker threads but the worst case
    # is a slightly off summary number — fine for telemetry.
    tier_counts: dict[CascadeTier, int] = {t: 0 for t in CascadeTier}
    _probed_count: int = 0  # used only for throttled log output

    def _handle_result(f: Path, is_lossy_val: bool | None, tier: CascadeTier | None) -> None:
        nonlocal _probed_count
        row = path_to_row[f]
        classify(
            row, is_lossy_val, lossy_action, no_lossy_check,
            input_root, source_root, output_root, preset,
        )
        if index_builder is not None:
            index_builder.add(row)
        if is_lossy_val:
            lossy_files_found.append(f)
        _probed_count += 1
        # Throttle log output: emit every 50 results + the final result.
        # Always log the first 3 and the last file so the user sees a sample
        # early and gets confirmation the phase is still running at the end.
        is_last = (_probed_count == total)
        should_log = is_last or _probed_count <= 3 or _probed_count % 50 == 0
        if should_log and hasattr(progress, "log_file"):
            tier_tag = f"[{tier.value}]" if tier is not None else ""
            progress.log_file(
                f"  {tier_tag:>10} {f.name} -> {row.job_type} "
                f"{'[LOSSY]' if is_lossy_val else ''}"
            )
        progress.advance()

    if no_lossy_check:
        progress.start_phase("Probing", total=total)
        for f in files:
            _handle_result(f, None, None)
        progress.stop()
        return lossy_files_found

    # ── Per-file cascade ────────────────────────────────────────────────
    # All files go into a single ThreadPoolExecutor. Each worker runs the
    # full three-tier cascade on its assigned file. Tier 1 and Tier 2 are
    # zero-I/O (string ops only) so they finish in microseconds; only
    # Tier 3 actually opens the file. By parallelising across files
    # rather than across tiers we avoid the previous "all 26k files
    # race through Tier 1, then 25k sit idle while Tier 2 runs, then
    # 24k sit idle while Tier 3 runs" pattern — every worker is always
    # busy on the deepest tier its current file requires.
    def probe_one(file: Path) -> tuple[Path, bool | None, CascadeTier]:
        try:
            is_lossy_val, tier = cascade_with_tier(file)
            return file, is_lossy_val, tier
        except Exception:
            return file, None, CascadeTier.MUTAGEN

    def _label_for(tier: CascadeTier) -> str:
        # Compact labels for the single progress bar.
        return {
            CascadeTier.EXTENSION: "Probing [Extension]",
            CascadeTier.FOLDER: "Probing [Folder]",
            CascadeTier.MUTAGEN: "Probing [Mutagen]",
        }[tier]

    progress.start_phase("Probing [Extension]", total=total)

    with ThreadPoolExecutor(max_workers=probe_workers) as executor:
        for infile, is_lossy_val, tier in executor.map(probe_one, files):
            tier_counts[tier] += 1
            # Update the bar label to reflect which tier resolved the
            # most recent file. Subsequent calls with the same label
            # are cheap (set + _refresh).
            progress.set_phase_label(_label_for(tier))
            _handle_result(infile, is_lossy_val, tier)

    progress.log(
        f"Probe complete: {tier_counts[CascadeTier.EXTENSION]} extension, "
        f"{tier_counts[CascadeTier.FOLDER]} folder, "
        f"{tier_counts[CascadeTier.MUTAGEN]} mutagen, "
        f"{len(lossy_files_found)} lossy"
    )
    progress.stop_phase()
    return lossy_files_found


def enrich_index_rows(
    rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
) -> list[Path]:
    """Fill ``dest_path``, ``job_type``, and ``is_lossy`` on each IndexRow in place.

    This is the blocking convenience wrapper. For live progress and incremental index
    DB writes, use :func:`enrich_index_rows_streaming` instead.

    Returns:
        List of source paths that are lossy (for the lossy-action gate).
    """
    files = [Path(r.source_path) for r in rows]

    if no_lossy_check:
        is_lossy_map: dict[Path, bool | None] = {f: None for f in files}
    else:
        is_lossy_map = probe_many(files, probe_workers)

    lossy_files_found: list[Path] = []

    for row in rows:
        f = Path(row.source_path)
        is_lossy = is_lossy_map.get(f)

        job_type = decide_job_type(is_lossy, lossy_action, no_lossy_check)

        # Mutate the row in place (IndexRow is frozen, so build a new one).
        # We rebuild the dataclass by replacing fields on the frozen object.
        object.__setattr__(row, "is_lossy", is_lossy)
        object.__setattr__(row, "job_type", job_type)

        outfile = compute_output_path(
            f,
            input_root,
            source_root,
            output_root,
            preset.ext,
        )
        object.__setattr__(row, "dest_path", str(outfile))

        if is_lossy:
            lossy_files_found.append(f)

    return lossy_files_found
