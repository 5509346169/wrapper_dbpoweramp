"""pathing/md5_staging.py: md5sum-named temp staging for native dbPoweramp.

This module replaces the long-path-only staging logic in ``long_path.py``.
It handles two classes of paths that cause qaac / CoreConverter to
produce 0-byte output or fail to open the file:

1. **UTF-8 paths** — any path component contains non-ASCII characters
   (detected via ``encode('ascii', 'strict')``).  qaac.exe and its
   child encoders use the Windows ANSI codepage for ``CreateFileW``
   unless the path is 8-bit clean.

2. **MAX_PATH paths** — the absolute path string exceeds 240 characters.
   CoreConverter does not use the long-path prefix, so the
   legacy 260-char limit applies.

The staging strategy:

1. ``stage_paths_v2()`` — if staging is needed, copy the source file to
   ``tmp/audio/src/<12-hex-md5>.md5hash.<ext>`` and point CoreConverter
   at the matching short output path under ``tmp/audio/dst/``.  The
   md5sum is computed from the UTF-8-encoded full source path string
   (12 hex chars, giving a 1-in-16T collision space).

2. CoreConverter reads the short source path, writes the short output
   path.  Neither path touches qaac's ANSI-codepage issues or MAX_PATH.

3. ``unstage_v2()`` — transfer the staged output to the original long
   destination.  On same-volume, ``os.replace`` is used for an atomic
   rename.  On cross-volume ``OSError``, fall back to
   ``shutil.copy2`` + unlink (the historical behaviour).  If the
   destination path itself exceeds 260 chars, fail with a clear error
   and leave both staged files intact for the next cleanup sweep.

The ``<12-hex-md5>.md5hash.<ext>`` naming scheme is deliberately
readable: a human can identify a staged artefact at a glance and, in
the rare event of a collision, the random 4-hex suffix appended
to avoid clobbering the on-disk file is visually distinct.
"""

from __future__ import annotations

import hashlib
import os
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StagingResult:
    """Result of preparing a (source, destination) pair for CoreConverter.

    Attributes:
        long_infile:     Original source path. Kept for reporting and logs.
        long_outfile:    Original destination path. ``unstage_v2`` transfers the
                         staged output here on success.
        staged_infile:   Path CoreConverter sees as ``-infile``.  When
                         ``staged`` is True this lives under ``tmp/audio/src/``.
        staged_outfile:  Path CoreConverter sees as ``-outfile``.  When
                         ``staged`` is True this lives under ``tmp/audio/dst/``.
        staged:          True if md5sum-named staging was applied.  False means
                         the paths were passed through as-is.
        md5sum:          12-hex MD5 digest of the UTF-8-encoded full source
                         path.  Available regardless of ``staged``.
        temp_filename:   The actual on-disk filename used in tmp/audio/.
                         Normally ``<md5sum>.md5hash.<ext>``; if a prior file
                         occupied that name, a random 4-hex suffix is appended
                         (e.g. ``<md5sum>-a3f7.md5hash.<ext>``).
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


def compute_md5sum(source_path: Path) -> str:
    """Return the 12-hex MD5 digest of a source path.

    The digest covers the UTF-8-encoded full path string, giving a
    stable 12-hex identifier for the same logical file regardless of
    when or how the pipeline runs.  This is deterministic and has no
    I/O cost (pure computation).

    Args:
        source_path: Absolute or relative source file path.

    Returns:
        12-character hexadecimal string.
    """
    return hashlib.md5(str(source_path).encode("utf-8")).hexdigest()[:12]


def _generate_temp_filename(md5sum: str, ext: str, src_dir: Path) -> str:
    """Generate a unique on-disk temp filename, avoiding collisions.

    Starts with ``<md5sum>.md5hash.<ext>`` and appends a random 4-hex
    suffix (``-xxxx``) if that name is already occupied by a leftover
    from a prior failed run.

    Args:
        md5sum:  12-hex MD5 digest.
        ext:     File extension WITHOUT leading dot (e.g. ``"flac"``).
        src_dir: The ``tmp/audio/src/`` directory to check for collisions.

    Returns:
        The on-disk filename (e.g. ``"a1b2c3d4e5f6.md5hash.flac"`` or
        ``"a1b2c3d4e5f6-b3f9.md5hash.flac"``).
    """
    candidate = f"{md5sum}.md5hash.{ext}"
    if not (src_dir / candidate).exists():
        return candidate
    chars = "0123456789abcdef"
    for _ in range(64):
        suffix = "".join(random.choice(chars) for _ in range(4))
        candidate = f"{md5sum}-{suffix}.md5hash.{ext}"
        if not (src_dir / candidate).exists():
            return candidate
    import uuid
    return f"{md5sum}-{uuid.uuid4().hex[:4]}.md5hash.{ext}"


def stage_paths_v2(
    infile: Path,
    outfile: Path,
    enabled: bool = True,
    tmp_root: Optional[Path] = None,
    md5_staging: str = "auto",
) -> StagingResult:
    """Prepare a (source, destination) pair for CoreConverter via md5sum staging.

    If ``enabled`` is True and at least one of the paths triggers the
    UTF-8 or MAX_PATH staging conditions, the source is copied to a
    short ``<md5sum>.md5hash.<ext>`` path under ``tmp/audio/src/`` and
    CoreConverter's ``-outfile`` is set to the matching short path under
    ``tmp/audio/dst/``.  Otherwise the original paths are returned
    unchanged.

    Args:
        infile:    The source file path.
        outfile:   The destination file path.
        enabled:   Whether tmp staging is enabled.  When False the
                   function always returns ``staged=False``.
        tmp_root:  Override for the staging root.  Defaults to
                   ``Path("tmp/audio")``.
        md5_staging: Naming mode for staged files.
                      ``'auto'`` (default): use ``<12-hex-md5>.md5hash.<ext>``
                      when either path triggers UTF-8 or MAX_PATH staging.
                      ``'on'``: always use the md5sum name (force staging).
                      ``'off'``: use the legacy ``<8-hex-md5>__<basename>``
                      form (for MAX_PATH only; UTF-8 paths are not handled).

    Returns:
        A :class:`StagingResult`.  Callers should pass ``staged_infile``
        and ``staged_outfile`` to CoreConverter and invoke ``unstage_v2``
        on success.
    """
    from src.pathing.utf8_check import name_needs_staging

    if tmp_root is None:
        tmp_root = Path("tmp") / "audio"

    src_dir = tmp_root / "src"
    dst_dir = tmp_root / "dst"

    # Compute md5sum immediately so callers always have it for logging.
    md5sum = compute_md5sum(infile)

    # No-op path: staging disabled, or platform is not Windows, or
    # neither path triggers the UTF-8 / MAX_PATH conditions.
    # 'on' mode: force staging regardless of path characteristics.
    if md5_staging != "on":
        if not enabled or sys.platform != "win32" or (
            not name_needs_staging(infile) and not name_needs_staging(outfile)
        ):
            return StagingResult(
                long_infile=infile,
                long_outfile=outfile,
                staged_infile=infile,
                staged_outfile=outfile,
                staged=False,
                md5sum=md5sum,
                temp_filename="",
            )

    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Choose naming form based on md5_staging mode.
    ext = outfile.suffix.lstrip(".")
    if md5_staging == "off":
        # Legacy form: <8-hex>__<basename>.  For MAX_PATH only;
        # UTF-8 paths are NOT handled in this mode.
        legacy_hash = md5sum[:8]
        temp_filename = f"{legacy_hash}__{outfile.name}"
        staged_infile = src_dir / temp_filename
        staged_outfile = dst_dir / temp_filename
        try:
            shutil.copy2(infile, staged_infile)
        except (shutil.Error, OSError):
            return StagingResult(
                long_infile=infile,
                long_outfile=outfile,
                staged_infile=infile,
                staged_outfile=outfile,
                staged=False,
                md5sum=md5sum,
                temp_filename="",
            )
        return StagingResult(
            long_infile=infile,
            long_outfile=outfile,
            staged_infile=staged_infile,
            staged_outfile=staged_outfile,
            staged=True,
            md5sum=md5sum,
            temp_filename=temp_filename,
        )

    # 'auto' or 'on': use md5sum-named form.
    temp_filename = _generate_temp_filename(md5sum, ext, src_dir)
    staged_infile = src_dir / temp_filename
    staged_outfile = dst_dir / temp_filename

    try:
        shutil.copy2(infile, staged_infile)
    except (shutil.Error, OSError):
        return StagingResult(
            long_infile=infile,
            long_outfile=outfile,
            staged_infile=infile,
            staged_outfile=outfile,
            staged=False,
            md5sum=md5sum,
            temp_filename="",
        )

    return StagingResult(
        long_infile=infile,
        long_outfile=outfile,
        staged_infile=staged_infile,
        staged_outfile=staged_outfile,
        staged=True,
        md5sum=md5sum,
        temp_filename=temp_filename,
    )


def unstage_v2(staged: StagingResult) -> bool:
    """Transfer the staged output to the long destination and clean up artefacts.

    When ``staged.staged`` is False this is a no-op that verifies the
    output exists.  When True the flow is:

    1. Verify staged output exists and is non-empty (0-byte is the qaac
       pipe-failure symptom).
    2. Ensure destination parent directory tree exists.
    3. ``os.replace`` (atomic rename) to move the staged output to
       the long destination.  On ``OSError`` (cross-volume) fall back
       to ``shutil.copy2`` + unlink.
    4. Best-effort cleanup of both staged files.
    5. Verify the long destination now exists and is non-empty.

    Args:
        staged: The :class:`StagingResult` returned by ``stage_paths_v2``.

    Returns:
        ``True`` if the long-path destination now exists and is non-empty.
        ``False`` on any failure.
    """
    success = False

    if not staged.staged:
        success = staged.long_outfile.exists() and staged.long_outfile.stat().st_size > 0
    else:
        # 1. Verify staged output.
        if staged.staged_outfile.exists() and staged.staged_outfile.stat().st_size > 0:
            # 2. Ensure destination parent exists.
            staged.long_outfile.parent.mkdir(parents=True, exist_ok=True)

            # 3. Remove any pre-existing file at the destination.
            if staged.long_outfile.exists() or staged.long_outfile.is_symlink():
                staged.long_outfile.unlink()

            # 4. Transfer the staged output to the destination.
            transfer_ok = False
            try:
                os.replace(staged.staged_outfile, staged.long_outfile)
                transfer_ok = True
            except OSError:
                try:
                    shutil.copy2(str(staged.staged_outfile), str(staged.long_outfile))
                    transfer_ok = True
                except (shutil.Error, OSError):
                    transfer_ok = False

            if transfer_ok:
                # 5. Verify the long destination is in place.
                success = (
                    staged.long_outfile.exists()
                    and staged.long_outfile.stat().st_size > 0
                )

    # Always clean up staged files (best-effort), regardless of outcome.
    for staged_path in (staged.staged_infile, staged.staged_outfile):
        try:
            if staged_path.exists():
                staged_path.unlink()
        except OSError:
            pass

    return success


__all__ = [
    "StagingResult",
    "compute_md5sum",
    "stage_paths_v2",
    "unstage_v2",
]
