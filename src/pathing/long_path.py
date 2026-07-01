"""pathing/long_path.py: Windows long-path workaround via 8.3 short names.

Problem
-------
On Windows, dBpoweramp's ``CoreConverter.exe`` and the child encoder binaries
(e.g. ``qaac.exe``) call the Win32 ``CreateFileW`` API *without* the
``\\?\\`` long-path prefix. The legacy MAX_PATH limit (260 chars) therefore
applies: any source/destination path whose absolute form exceeds 260 chars
fails to open. The decoder never feeds PCM to the encoder's stdin pipe and
CoreConverter reports::

    Error writing audio data to StdIn Pipe  [clEncoder::EncodeBlock]

with a 0-byte output file. Repro: paths like ``D:\\MusicLossy\\AM-DL\\JP_en-US\\
AM-DL-ALAC\\Guchiry & Shishido [1438071892]\\Welcome, Ideology (feat. Hatsune
Miku, 鏡音リン, v4 flower, ...)\\1.04. Who Built The Hell_.m4a`` routinely exceed
260 chars on libraries with deeply nested artist/album folders.

Strategy
--------
Every NTFS file and directory has an associated 8.3 (DOS-era) short name. We
resolve the long path's parent directory to a short name, then re-attach the
original (long) basename. Both CoreConverter and the encoder see only the
short paths on the command line — well within MAX_PATH — and the conversion
succeeds.

Because on a single NTFS volume the short path is just an alias for the same
physical file (same inode, verified empirically), the encoder's write is
already visible at the long path the moment it completes. ``unstage()``
therefore only checks that the long-path output exists and is non-empty; no
explicit rename is needed. The history DB always sees the long paths so the
resume logic is unaffected.

This is opt-in via ``backend.native_dbpoweramp.long_paths: true`` (settings)
or ``--long-paths`` (CLI). On non-Windows platforms or when 8.3 names are
disabled on the volume, this module degrades to a no-op (returns the input
path unchanged) so the wrapper keeps working unchanged.

References
----------
* Microsoft: "Naming Files, Paths, and Namespaces" — MAX_PATH limits.
* ``fsutil 8dot3name`` — per-volume 8.3 name generation toggle.
"""
from __future__ import annotations

import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Leave headroom below the legacy 260 MAX_PATH for the CoreConverter command
# line (the path appears inside `-outfile="..."`, so a 260-char path on disk
# turns into a ~280-char token on the command line). We stage anything past
# this threshold.
_MAX_PATH_SAFE = 240

# Match MAX_PATH itself: any path strictly longer than this is at risk on
# Win32 binaries that don't opt into the long-path aware Win32 APIs.
_MAX_PATH = 260


@dataclass(frozen=True)
class StagingResult:
    """The result of preparing a (long) source/destination pair for conversion.

    Attributes:
        infile:     Path to pass to CoreConverter as ``-infile`` (short form).
        outfile:    Path to pass to CoreConverter as ``-outfile`` (short form).
        staged:     True if long-path staging was actually applied. False means
                    the input was already short enough or the platform doesn't
                    support staging — the caller should use the long paths
                    directly.
        long_outfile:  The original long destination path. After the subprocess
                    returns SUCCESS, the caller should move ``outfile`` back
                    to ``long_outfile``.
    """

    infile: Path
    outfile: Path
    staged: bool
    long_outfile: Path


def _get_short_path_name_windows(path: str) -> Optional[str]:
    """Resolve a path to its 8.3 short name via Win32 ``GetShortPathNameW``.

    Returns ``None`` if the path doesn't exist or if the volume has 8.3 name
    generation disabled (in which case GetShortPathNameW returns the input
    unchanged — but only when the input is already short; we detect the
    no-op by comparing against the input length).
    """
    if sys.platform != "win32":
        return None

    # Lazy import: ctypes.windll is only available on Windows.
    import ctypes

    GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
    GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    GetShortPathNameW.restype = wintypes.DWORD

    buf_len = 4096
    buf = ctypes.create_unicode_buffer(buf_len)
    n = GetShortPathNameW(path, buf, buf_len)
    if n == 0:
        # Path doesn't exist or some other Win32 error; the caller should
        # fall back to the long path and let CoreConverter surface its own
        # error.
        return None
    return buf.value


def _short_path_for(path: Path) -> Optional[str]:
    """Return the 8.3 short path for *path*'s parent directory + long basename.

    The destination file may not exist yet, so we resolve the parent
    directory's short name (which is guaranteed to exist by the time the
    caller invokes us) and re-attach the long leaf name.
    """
    if sys.platform != "win32":
        return None

    if path.exists():
        short = _get_short_path_name_windows(str(path))
        if short is not None:
            return short

    # Fall back to resolving the parent directory's short name.
    parent = path.parent
    if not parent.exists():
        return None
    short_parent = _get_short_path_name_windows(str(parent))
    if short_parent is None:
        return None
    return str(Path(short_parent) / path.name)


def _path_is_long(path: Path) -> bool:
    """Return True iff *path* exceeds the MAX_PATH safety threshold."""
    return len(str(path)) > _MAX_PATH_SAFE


def stage_paths(
    infile: Path,
    outfile: Path,
    enabled: bool,
) -> StagingResult:
    """Prepare a (source, destination) pair for CoreConverter.

    If long-path staging is *enabled* and either path is long enough to risk
    MAX_PATH, both paths are rewritten to their 8.3 short form. Otherwise the
    original paths are returned unchanged.

    The caller MUST create ``outfile.parent`` (with mkdir parents=True) before
    invoking this — the destination directory needs to exist on disk so that
    its short name resolves.

    Args:
        infile:  The long source path.
        outfile: The long destination path.
        enabled: Whether long-path staging is enabled (CLI flag or settings).

    Returns:
        A :class:`StagingResult` describing what to pass to CoreConverter and
        what to move the output back to on success.
    """
    long_outfile = outfile

    if not enabled or sys.platform != "win32":
        return StagingResult(
            infile=infile, outfile=outfile, staged=False, long_outfile=long_outfile,
        )

    if not _path_is_long(infile) and not _path_is_long(outfile):
        return StagingResult(
            infile=infile, outfile=outfile, staged=False, long_outfile=long_outfile,
        )

    short_in = _short_path_for(infile)
    short_out = _short_path_for(outfile)

    # If we can't resolve either, fall back to the long path. CoreConverter
    # will surface a clearer error than a confusing "short path" missing.
    if short_in is None or short_out is None:
        return StagingResult(
            infile=infile, outfile=outfile, staged=False, long_outfile=long_outfile,
        )

    # Sanity check: the short paths must actually be shorter, otherwise
    # the volume has 8.3 names disabled and we're not helping anyone by
    # claiming "staged=True".
    if len(short_in) >= len(str(infile)) or len(short_out) >= len(str(outfile)):
        return StagingResult(
            infile=infile, outfile=outfile, staged=False, long_outfile=long_outfile,
        )

    return StagingResult(
        infile=Path(short_in),
        outfile=Path(short_out),
        staged=True,
        long_outfile=long_outfile,
    )


def unstage(staged: StagingResult) -> bool:
    """Verify the long-path output now exists after staging.

    On a single NTFS volume, the short path returned by ``GetShortPathNameW``
    is just a 8.3 alias for the same physical file — writing through one
    name immediately updates the other (verified by inode equality). So
    there is nothing to rename; we only need to confirm the long-path
    destination is now on disk and non-empty.

    Returns ``True`` if the long-path output exists and is non-empty,
    ``False`` otherwise. The caller is expected to check ``staged.staged``
    before invoking this — no-op when staging was not applied.
    """
    if not staged.staged:
        return True

    if not staged.long_outfile.exists():
        return False
    return staged.long_outfile.stat().st_size > 0


__all__ = [
    "StagingResult",
    "stage_paths",
    "unstage",
    "_MAX_PATH",
    "_MAX_PATH_SAFE",
]