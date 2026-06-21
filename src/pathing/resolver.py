"""pathing/resolver.py: Path resolution logic for input/output tree mapping."""

import os
import shutil
import subprocess
from pathlib import Path

from src.exceptions import BackendError, PathConfigError


def compute_output_path(
    infile: Path,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    target_ext: str,
) -> Path:
    """
    Compute the output path for a given input file.

    Mirrors the original script's rel_path logic, but relative-to source_root when given.

    - If source_root is None: behave exactly like the original (relative to input_root,
      or just the bare filename if input_root is a single file).
    - If source_root is given: rel_path = infile.relative_to(source_root); this lets
      `--input` point at a subfolder while output still reproduces the full library tree.

    Args:
        infile: The input file path.
        input_root: The root of the input path (either a directory or a file).
        source_root: If given, use this as the base for computing the relative path.
        output_root: The root directory for output files.
        target_ext: The target file extension (e.g., '.mp3').

    Returns:
        The computed output path.
    """
    if source_root is not None:
        # Use source_root as the base for relative path computation
        rel_path = infile.relative_to(source_root)
        return output_root / rel_path.with_suffix(target_ext)

    # source_root is None: behave like the original script
    if infile == input_root:
        # input_root is a single file (same as infile): output is output_root with just the bare filename
        return output_root / infile.with_suffix(target_ext).name
    else:
        # input_root is a directory: output is output_root / infile.relative_to(input_root)
        rel_path = infile.relative_to(input_root)
        return output_root / rel_path.with_suffix(target_ext)


def validate_source_path(input_path: Path, source_path: Path) -> None:
    """
    Validate that input_path is source_path or inside it.

    Raises PathConfigError if input_path is not source_path or inside it.

    Args:
        input_path: The input path to validate.
        source_path: The expected source path ancestor.

    Raises:
        PathConfigError: If input_path is not source_path or inside it.
    """
    if not input_path.is_relative_to(source_path):
        raise PathConfigError(
            f"PathConfigError: --source-path {source_path} is not an ancestor of --input {input_path}"
        )


def hide_filename(name: str) -> str:
    """
    Hide a filename by prefixing it with a dot.

    'cover.jpg' -> '.cover.jpg'.
    No-op if name already starts with '.'.

    Args:
        name: The filename to potentially hide.

    Returns:
        The filename with a dot prefix if it wasn't already hidden.
    """
    if name.startswith("."):
        return name
    return "." + name


def to_wine_path(
    linux_path: Path,
    wine_binary: str,
    wine_prefix: str,
    winepath_binary: str,
) -> str:
    """
    Translate a Linux path to a Windows path using winepath.

    Shells out to `winepath -w <path>` with WINEPREFIX=wine_prefix set, returns the
    Windows-style path string Wine/CoreConverter expects.

    Args:
        linux_path: The Linux path to translate.
        wine_binary: The wine binary name or path.
        wine_prefix: The WINEPREFIX directory path.
        winepath_binary: The winepath binary name or path.

    Returns:
        The Windows-style path string.

    Raises:
        BackendError: If winepath is missing or exits non-zero.
    """
    # Check if wine and winepath binaries are available
    if shutil.which(wine_binary) is None:
        raise BackendError(f"BackendError: wine binary '{wine_binary}' not found in PATH")
    if shutil.which(winepath_binary) is None:
        raise BackendError(f"BackendError: winepath binary '{winepath_binary}' not found in PATH")

    # Build args list with shell=False
    args = [winepath_binary, "-w", str(linux_path)]

    # Build environment with WINEPREFIX merged with existing env
    env = os.environ.copy()
    env["WINEPREFIX"] = wine_prefix

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        shell=False,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise BackendError(f"BackendError: winepath failed: {result.stderr.strip()}")

    return result.stdout.strip()
