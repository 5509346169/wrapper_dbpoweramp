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

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from src.audio.inspector import (
    _is_lossy_by_ext,
    _is_lossy_by_folder,
    _is_lossy_by_mutagen,
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

    Detection cascade (phases shown only when they have work):
      1. Extension — non-.m4a files only; .m4a is always ambiguous and skipped.
      2. Folder  — non-.m4a files not resolved by extension.
      3. Mutagen — all remaining files (including all .m4a).

    Each phase gets its own progress bar so the user sees meaningful progress at
    each stage rather than a single bar for the combined total.

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
    resolved: set[Path] = set()

    def _handle_result(f: Path, is_lossy_val: bool | None) -> None:
        row = path_to_row[f]
        classify(
            row, is_lossy_val, lossy_action, no_lossy_check,
            input_root, source_root, output_root, preset,
        )
        if index_builder is not None:
            index_builder.add(row)
        if is_lossy_val:
            lossy_files_found.append(f)
        if hasattr(progress, "log_file"):
            progress.log_file(f"  {f.name} -> {row.job_type} {'[LOSSY]' if is_lossy_val else ''}")
        progress.advance()

    def _phase_mutagen(files_to_probe: list[Path]) -> None:
        if not files_to_probe:
            return
        if hasattr(progress, "log_phase"):
            progress.log_phase("Mutagen")
        else:
            progress.log(f"Probing {len(files_to_probe)} files with mutagen ({probe_workers} workers)...")

        def probe_one(file: Path) -> tuple[Path, bool]:
            return (file, _is_lossy_by_mutagen(file))

        with ThreadPoolExecutor(max_workers=probe_workers) as executor:
            future_map: dict[Future, Path] = {
                executor.submit(probe_one, f): f for f in files_to_probe
            }
            for future in as_completed(future_map):
                infile = future_map[future]
                try:
                    _, is_lossy_val = future.result()
                except Exception:
                    is_lossy_val = None
                _handle_result(infile, is_lossy_val)

    if no_lossy_check:
        progress.start_phase("Probing", total=total)
        for f in files:
            _handle_result(f, None)
    else:
        # Single-pass split: classify each file by extension and reuse the
        # boolean flag — avoids the previous O(n*m4a) ``f in set(m4a_files)``
        # comparison that became a hotspot on 20k+ file inputs.
        file_is_m4a: dict[Path, bool] = {f: (f.suffix.lower() == ".m4a") for f in files}
        m4a_files = [f for f, is_m4a in file_is_m4a.items() if is_m4a]
        non_m4a_files = [f for f, is_m4a in file_is_m4a.items() if not is_m4a]

        # ── Phase 1: Extension (non-.m4a only) ──────────────────────────────
        if non_m4a_files:
            progress.start_phase("Extension", total=len(non_m4a_files))
            for f in non_m4a_files:
                ext_val = _is_lossy_by_ext(f)
                if ext_val is not None:
                    _handle_result(f, ext_val)
                    resolved.add(f)
                else:
                    progress.advance()

        # ── Phase 2: Folder (non-.m4a not resolved by extension) ──────────────
        remaining_non_m4a = [f for f in non_m4a_files if f not in resolved]
        if remaining_non_m4a:
            progress.start_phase("Folder", total=len(remaining_non_m4a))
            for f in remaining_non_m4a:
                folder_val = _is_lossy_by_folder(f)
                if folder_val is not None:
                    _handle_result(f, folder_val)
                    resolved.add(f)
                else:
                    progress.advance()

        # ── Phase 3: Mutagen (remaining non-.m4a + all .m4a) ──────────────────
        remaining = [f for f in files if f not in resolved]
        _phase_mutagen(remaining)

        if not hasattr(progress, "log_file"):
            progress.log(f"Probing done. {len(lossy_files_found)} lossy file(s) found.")
        elif lossy_files_found:
            progress.log_file(f"  Total lossy files: {len(lossy_files_found)}")

    progress.stop()
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
