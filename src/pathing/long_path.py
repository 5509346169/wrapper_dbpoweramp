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

import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Leave headroom below the legacy 260 MAX_PATH for the CoreConverter command
# line (the path appears inside `-outfile="..."`, so a 260-char path on disk
# turns into a ~280-char token on the command line). We stage anything past
# this threshold.
_MAX_PATH_SAFE = 240


@dataclass(frozen=True)
class StagingResult:
    """The result of preparing a (long) source/destination pair for conversion.

    Attributes:
        long_infile:      Original (long) source path. Kept around for
                          reporting + log lines.
        long_outfile:     Original (long) destination path. After the
                          subprocess returns SUCCESS, the caller invokes
                          ``unstage()`` to move ``staged_outfile`` here.
        staged_infile:    Path CoreConverter sees as ``-infile``. Short
                          form, lives under ``tmp_root/audio/src/``.
        staged_outfile:   Path CoreConverter sees as ``-outfile``. Short
                          form, lives under ``tmp_root/audio/dst/``.
        staged:           True if long-path staging was applied. False
                          means the paths were already short (or staging
                          was disabled) and the caller should use the
                          long paths directly.
    """

    long_infile: Path
    long_outfile: Path
    staged_infile: Path
    staged_outfile: Path
    staged: bool

    # Back-compat aliases — the previous 8.3 implementation exposed
    # ``infile`` / ``outfile`` as the short forms. Keep them so callers
    # can read whichever name reads better in context.
    @property
    def infile(self) -> Path:
        """Alias for ``staged_infile`` — the path to pass to CoreConverter."""
        return self.staged_infile

    @property
    def outfile(self) -> Path:
        """Alias for ``staged_outfile`` — the path to pass to CoreConverter."""
        return self.staged_outfile


def _short_hash(path: Path, length: int = 8) -> str:
    """Stable short hash of a path string for staging-name disambiguation.

    Two distinct source files that happen to share the same basename
    (e.g. ``track01.m4a`` in two different albums) must not collide in
    the staging directory. We use a short MD5 prefix of the *full long
    source path* as a discriminator — that gives us a stable, collision-
    resistant, ASCII-safe prefix.

    MD5 is used purely for uniqueness, not security; any fast hash would
    do, but ``hashlib.md5`` is in the stdlib and faster than ``sha256``
    for this short-prefix use case.
    """
    digest = hashlib.md5(str(path).encode("utf-8", errors="replace")).hexdigest()
    return digest[:length]


def _path_is_long(path: Path) -> bool:
    """Return True iff *path* exceeds the MAX_PATH safety threshold."""
    return len(str(path)) > _MAX_PATH_SAFE


def stage_paths(
    infile: Path,
    outfile: Path,
    enabled: bool,
    tmp_root: Optional[Path] = None,
) -> StagingResult:
    """Prepare a (source, destination) pair for CoreConverter.

    If long-path staging is *enabled* and either path is long enough to
    risk MAX_PATH, the source is copied into ``tmp_root/audio/src/<hash>__
    <basename>.<ext>`` and CoreConverter's ``-outfile`` is set to
    ``tmp_root/audio/dst/<hash>__<basename>.<ext>``. Otherwise the
    original paths are returned unchanged.

    Args:
        infile:  The (possibly long) source path.
        outfile: The (possibly long) destination path.
        enabled: Whether tmp staging is enabled (CLI flag or settings).
        tmp_root: Optional override for the staging root. Defaults to
            ``Path("tmp/audio")``. Must already exist with ``src/`` and
            ``dst/`` subdirectories (created by ``setup_temp_dir()``).

    Returns:
        A :class:`StagingResult` describing what to pass to CoreConverter
        and what to move the output back to on success. The ``staged``
        flag indicates whether staging was actually applied.
    """
    if tmp_root is None:
        tmp_root = Path("tmp") / "audio"

    src_dir = tmp_root / "src"
    dst_dir = tmp_root / "dst"

    # No-op path: staging disabled, or both paths already short enough.
    if (
        not enabled
        or sys.platform != "win32"
        or (not _path_is_long(infile) and not _path_is_long(outfile))
    ):
        return StagingResult(
            long_infile=infile,
            long_outfile=outfile,
            staged_infile=infile,
            staged_outfile=outfile,
            staged=False,
        )

    # Generate a unique staged basename: ``<hash>__<stem>.<ext>``. The
    # hash prevents collisions between jobs whose source files share a
    # basename but live in different folders.
    hash_prefix = _short_hash(infile)
    staged_basename = f"{hash_prefix}__{outfile.name}"

    staged_infile = src_dir / staged_basename
    staged_outfile = dst_dir / staged_basename

    # Defensive: ensure both directories exist. setup_temp_dir() should
    # have created them, but if the user ran with --no-scan-cache or
    # something else that skipped temp setup, we create on demand.
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Copy the source so CoreConverter sees a stable snapshot at a short
    # path. shutil.copy2 preserves mtime; we don't rely on it but it's
    # free metadata for downstream tools (e.g. a manual ``ls``).
    try:
        shutil.copy2(infile, staged_infile)
    except (shutil.Error, OSError):
        # If the copy itself fails (e.g. source vanished, permission
        # denied, disk full), fall back to the long paths and let
        # CoreConverter surface a clear error. We've already mkdir'd
        # both staging dirs, which is harmless if we never use them.
        return StagingResult(
            long_infile=infile,
            long_outfile=outfile,
            staged_infile=infile,
            staged_outfile=outfile,
            staged=False,
        )

    return StagingResult(
        long_infile=infile,
        long_outfile=outfile,
        staged_infile=staged_infile,
        staged_outfile=staged_outfile,
        staged=True,
    )


def unstage(staged: StagingResult) -> bool:
    """Copy the staged output to the long destination and clean up both
    staging artefacts.

    The full flow this implements is literally::

        1. stage_paths()      : shutil.copy2(long_infile,  tmp/audio/src/<hash>__<basename>)
        2. CoreConverter runs : writes tmp/audio/src/<hash>__<basename>
                                -> tmp/audio/dst/<hash>__<basename>
        3. unstage()          : shutil.copy2(tmp/audio/dst/<hash>__<basename>,
                                            long_outfile)
                                then unlink(tmp/audio/dst/<hash>__<basename>)
                                (staged source was already unlinked at start
                                of step 3 — see below)

    On success:

      * Creates the long-path destination's parent directory tree.
      * Removes any pre-existing file at the long destination (so a retry
        overwrites a stale partial output — the ``--failed-only`` semantics
        depend on this).
      * ``shutil.copy2()``'s the staged output to the long destination —
        a literal byte-for-byte copy. We deliberately use ``copy2`` and
        not ``shutil.move``: we want the staged output to remain on disk
        during the copy so a mid-copy error leaves a recoverable artefact
        in ``tmp/audio/dst/`` instead of moving-and-corrupting the
        destination.
      * Unlinks the staged output (no longer needed — the long
        destination now has its own copy).
      * Unlinks the staged source too, if it's still around (it
        normally would have been cleared at the start of the step, but
        if the source-copy failed earlier we want to make sure no stale
        file leaks into the next job).

    Returns ``True`` if the long-path output now exists and is non-empty,
    ``False`` otherwise. The caller is expected to check ``staged.staged``
    before invoking this — no-op when staging was not applied.

    The function never raises on filesystem errors: a missing staged
    output, a permission error during copy, or a full destination volume
    all surface as ``False`` so the caller can report a unified error
    message ("CoreConverter exited 0 but the expected output at <long
    path> is missing or empty").
    """
    if not staged.staged:
        # No staging was applied — verify the long-path output exists
        # and is non-empty (matches the previous 8.3 short-name
        # verification behaviour).
        if not staged.long_outfile.exists():
            return False
        return staged.long_outfile.stat().st_size > 0

    try:
        # 0. Defensive cleanup of the staged source. stage_paths() copied
        # the long source here in step 1; once the encoder is done with
        # it, we don't need it any more. Best-effort — the per-job
        # cleanup is the real line of defence (next run clears
        # tmp/audio/src/ at startup), this just keeps the dir tidy.
        try:
            if staged.staged_infile.exists():
                staged.staged_infile.unlink()
        except OSError:
            pass

        # 1. Verify the staged output exists and is non-empty.
        if not staged.staged_outfile.exists():
            return False
        if staged.staged_outfile.stat().st_size == 0:
            # Encoder produced a blank file (the qaac-pipe-failure
            # symptom). Clean up the empty artefact and report failure
            # so the caller can mark the conversion as FAILED.
            try:
                staged.staged_outfile.unlink()
            except OSError:
                pass
            return False

        # 2. Ensure the destination parent directory exists. The user
        # might have deleted it between scan and convert (unlikely but
        # cheap to handle).
        staged.long_outfile.parent.mkdir(parents=True, exist_ok=True)

        # 3. Remove any pre-existing file at the long destination.
        # shutil.copy2 will refuse to overwrite on Windows in some
        # configurations; the explicit unlink guarantees a clean slate
        # and gives a clearer failure mode on read-only destination
        # volumes.
        if staged.long_outfile.exists() or staged.long_outfile.is_symlink():
            staged.long_outfile.unlink()

        # 4. Literal copy of the staged output to the long destination.
        # shutil.copy2 preserves metadata (mtime) where the underlying
        # filesystem supports it. We use copy2 (not move) so the
        # staged file stays around during the copy — if the destination
        # volume goes full or unlinks mid-write, the staged file is
        # still recoverable for inspection.
        shutil.copy2(str(staged.staged_outfile), str(staged.long_outfile))
    except (shutil.Error, OSError):
        return False
    finally:
        # Best-effort cleanup of the staged output. The long destination
        # already has its own copy by now (or we returned False because
        # the copy raised), so the staged file is no longer needed.
        try:
            if staged.staged_outfile.exists():
                staged.staged_outfile.unlink()
        except OSError:
            pass

        # Same for the staged source — defensive in case step 0 above
        # raised before unlinking.
        try:
            if staged.staged_infile.exists():
                staged.staged_infile.unlink()
        except OSError:
            pass

    # 5. Verify the long-path output is now in place and non-empty.
    if not staged.long_outfile.exists():
        return False
    return staged.long_outfile.stat().st_size > 0


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
]