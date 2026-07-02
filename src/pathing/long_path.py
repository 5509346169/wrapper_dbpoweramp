"""pathing/long_path.py: Windows long-path workaround via tmp-copy staging.

Problem
-------
On Windows, dBpoweramp's ``CoreConverter.exe`` and the child encoder binaries
(e.g. ``qaac.exe``) call the Win32 ``CreateFileW`` API *without* the
``\\\\?\\`` long-path prefix. The legacy MAX_PATH limit (260 chars) therefore
applies: any source/destination path whose absolute form exceeds 260 chars
fails to open. The decoder never feeds PCM to the encoder's stdin pipe and
CoreConverter reports::

    Error writing audio data to StdIn Pipe  [clEncoder::EncodeBlock]

with a 0-byte output file. Repro: paths like ``D:\\MusicLossy\\AM-DL\\
JP_en-US\\AM-DL-ALAC\\GUMI [406470856]\\Work On Mowing and Growing Vegetables
…\\1.02. Song of the Making of Vegetables (2019remix) [feat. Keitaro
Kikuchi].m4a`` routinely exceed 260 chars on libraries with deeply nested
artist/album folders (especially JP/en libraries with kanji + Roman names).

Strategy
--------
We avoid the problem entirely by staging each conversion to a short
*tmp* path that lives under ``./tmp/audio/``:

1. **Source copy** — the long source path is copied to
   ``tmp/audio/src/<hash>__<basename>.<ext>``. ``<hash>`` is an 8-char MD5
   prefix of the full long source path, guaranteeing uniqueness across the
   batch even when two different folders contain a ``track01.m4a`` with
   the same leaf name.

2. **Short destination** — CoreConverter's ``-outfile=`` is set to
   ``tmp/audio/dst/<hash>__<basename>.<ext>``. CoreConverter and qaac
   both see only short paths, so neither can trip MAX_PATH.

3. **Final copy** — once CoreConverter exits 0, ``unstage()`` performs a
   literal ``shutil.copy2()`` of the staged output at
   ``tmp/audio/dst/<hash>__<basename>.<ext>`` to the original long
   destination, then unlinks both the staged output and the staged
   source. We use ``copy2`` (not ``move``) so the staged output stays
   on disk during the copy — if the destination volume becomes full or
   unlinks mid-write, the staged file is still recoverable for
   inspection rather than moving-and-corrupting the destination.

This is more robust than the previous 8.3-short-name approach because:
  * It does not depend on per-volume 8.3 name generation being enabled
    (``fsutil 8dot3name``).
  * It does not depend on CoreConverter/qaac passing the short path through
    to every internal Win32 call (some encoders re-resolve the destination
    internally and may still hit MAX_PATH even with a short ``-outfile``).
  * It is portable: it works the same way on every NTFS volume, regardless
    of how it was formatted or mounted.

The I/O cost is one full source copy per job. For audio that is negligible
compared to the encoding cost (which is CPU-bound, not I/O-bound).

API
---
``stage_paths(infile, outfile, enabled, tmp_root)`` resolves a (long)
source/destination pair to short staged paths under ``tmp_root`` *only when*
``enabled`` is True and at least one of the paths exceeds the MAX_PATH
safety threshold (240 chars). For short paths the function is a no-op and
returns the original paths.

``unstage(staged)`` copies the staged output to the long destination
(``shutil.copy2``, a literal byte-for-byte copy — not a move) and
removes both the staged output and the staged source. Returns True on
success, False on failure (missing or empty output, write error during
the copy).

The full per-job flow is therefore an explicit three-step copy chain::

    1. stage_paths():  shutil.copy2(long_infile,  tmp/audio/src/<hash>__<basename>)
    2. CoreConverter:  writes tmp/audio/src/<hash>__<basename>
                       -> tmp/audio/dst/<hash>__<basename>
    3. unstage():      shutil.copy2(tmp/audio/dst/<hash>__<basename>,
                                   long_outfile) + cleanup of both staged files

Step 3 uses ``copy2`` (not ``move``) so the staged output stays on disk
during the copy — if the destination volume becomes full or unlinks
mid-write, the staged file is still recoverable for inspection rather
than moving-and-corrupting the destination.

This is opt-in via ``backend.native_dbpoweramp.tmp_staging: true``
(settings) or ``--tmp-staging`` (CLI). When the setting is off (default)
or the paths are short, the function is a no-op and the original long
paths are passed straight through to CoreConverter.

References
----------
* Microsoft: "Naming Files, Paths, and Namespaces" — MAX_PATH limits.
* ``shutil.move`` semantics — same-volume atomic rename, cross-volume
  copy+delete.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.pathing import md5_staging as _md5_staging
from src.pathing.md5_staging import compute_md5sum  # re-exported for callers importing from long_path

# Re-export _MAX_PATH_SAFE so external callers (e.g. tests) don't break.
_MAX_PATH_SAFE = 240


@dataclass
class StagingResult:
    """The result of preparing a (long) source/destination pair for conversion.

    Attributes:
        long_infile:     Original (long) source path. Kept around for
                         reporting + log lines.
        long_outfile:    Original (long) destination path. After the
                         subprocess returns SUCCESS, the caller invokes
                         ``unstage()`` to move ``staged_outfile`` here.
        staged_infile:   Path CoreConverter sees as ``-infile``. Short
                         form, lives under ``tmp_root/audio/src/``.
        staged_outfile:  Path CoreConverter sees as ``-outfile``. Short
                         form, lives under ``tmp_root/audio/dst/``.
        staged:          True if long-path staging was applied.  False
                         means the paths were already short (or staging
                         was disabled) and the caller should use the
                         long paths directly.
        md5sum:          12-hex MD5 digest of the UTF-8-encoded full
                         source path. Available regardless of ``staged``.
        temp_filename:   The actual on-disk filename used in tmp/audio/.
                         Empty string when ``staged`` is False.
    """

    long_infile: Path
    long_outfile: Path
    staged_infile: Path
    staged_outfile: Path
    staged: bool
    md5sum: str = ""
    temp_filename: str = ""

    @property
    def infile(self) -> Path:
        return self.staged_infile

    @property
    def outfile(self) -> Path:
        return self.staged_outfile


def _path_is_long(path: Path) -> bool:
    """Return True iff *path* exceeds the MAX_PATH safety threshold."""
    return len(str(path)) > _MAX_PATH_SAFE


def stage_paths(
    infile: Path,
    outfile: Path,
    enabled: bool,
    tmp_root: Optional[Path] = None,
    md5_staging: str = "auto",
) -> StagingResult:
    """Prepare a (source, destination) pair for CoreConverter.

    Delegates to ``src.pathing.md5_staging.stage_paths_v2()``, which
    handles both UTF-8 path safety and MAX_PATH avoidance via
    md5sum-named staging.  When staging is not needed the original
    paths are returned unchanged.

    Returns:
        A :class:`StagingResult`.
    """
    return _md5_staging.stage_paths_v2(
        infile=infile,
        outfile=outfile,
        enabled=enabled,
        tmp_root=tmp_root,
        md5_staging=md5_staging,
    )


def unstage(staged: StagingResult) -> bool:
    """Copy the staged output to the long destination and clean up artefacts.

    Delegates to ``src.pathing.md5_staging.unstage_v2()``.

    Returns ``True`` if the long-path output now exists and is non-empty.
    """
    return _md5_staging.unstage_v2(staged)


def cleanup_staging_workspace(tmp_root: Optional[Path] = None) -> None:
    """Delete every file in ``tmp_root/audio/src`` and ``tmp_root/audio/dst``.

    Called by ``run_pipeline.run()`` at startup so a previous failed run
    doesn't leave stale staged files lying around. Errors are swallowed —
    the worst case is that tmp fills up with orphaned files (the next
    run cleans them up).

    Args:
        tmp_root: Optional override. Defaults to ``Path("tmp/audio")``.
    """
    if tmp_root is None:
        tmp_root = Path("tmp") / "audio"
    for sub in ("src", "dst"):
        d = tmp_root / sub
        if not d.exists():
            continue
        for entry in d.iterdir():
            try:
                if entry.is_file() or entry.is_symlink():
                    entry.unlink()
                elif entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                # Best-effort: ignore — a leftover file is harmless.
                pass


__all__ = [
    "StagingResult",
    "stage_paths",
    "unstage",
    "cleanup_staging_workspace",
    "_MAX_PATH_SAFE",
    "compute_md5sum",
    "_path_is_long",
]