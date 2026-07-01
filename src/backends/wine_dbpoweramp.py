"""backends/wine_dbpoweramp.py: Wine + dBpoweramp CoreConverter conversion backend."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.backends.base import ConversionBackend
from src.config.settings_loader import Settings
from src.exceptions import BackendError
from src.models.types import (
    Backend,
    ConversionJob,
    JobResult,
    PresetConfig,
)
from src.pathing.resolver import to_wine_path


class WineDbpowerampBackend(ConversionBackend):
    """Conversion backend that runs dBpoweramp's CoreConverter.exe under Wine."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the Wine dBpoweramp backend.

        Args:
            settings: Application settings containing backend.wine_dbpoweramp config.
        """
        self._settings = settings
        self._wine_cfg = settings.backend.wine_dbpoweramp

    def name(self) -> Backend:
        """Return the backend identifier."""
        return Backend.WINE_DBPOWERAMP

    def _resolve_binary(self, binary: str) -> str:
        """Return the resolved path of a binary.

        Checks via shutil.which first, then falls back to checking if it's an
        absolute path to an existing file.

        Args:
            binary: Binary name or absolute path.

        Returns:
            The binary path as given (resolution is informational only).

        Raises:
            BackendError: If the binary cannot be resolved.
        """
        resolved = shutil.which(binary)
        if resolved is not None:
            return resolved
        p = Path(binary)
        if p.is_absolute() and p.is_file():
            return binary
        raise BackendError(
            f"BackendError: '{binary}' not found on PATH and is not an absolute path to an existing file.\n"
            "Install Wine from your distribution's package manager:\n"
            "  sudo pacman -S wine    (Arch/CachyOS)\n"
            "  sudo apt install wine  (Debian/Ubuntu)\n"
            "  sudo dnf install wine (Fedora)"
        )

    def validate_environment(self) -> None:
        """Check that required binaries/paths/prefix exist and that Wine actually runs.

        Raises BackendError with a human-readable, fix-it message if any check fails.
        """
        # 1. Resolve wine_binary
        self._resolve_binary(self._wine_cfg.wine_binary)

        # 2. Resolve winepath_binary
        self._resolve_binary(self._wine_cfg.winepath_binary)

        # 3. Check wine_prefix exists
        wine_prefix = self._wine_cfg.wine_prefix
        if not wine_prefix.exists():
            raise BackendError(
                f"BackendError: WINEPREFIX '{wine_prefix}' does not exist.\n"
                "Create it by running: WINEPREFIX=~/.wine-dbpoweramp wineboot\n"
                "Then install dBpoweramp into that prefix using a Windows installer under Wine."
            )

        # 4. Quick smoke-test: wine --version
        result = subprocess.run(
            [self._wine_cfg.wine_binary, "--version"],
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode != 0:
            raise BackendError(
                f"BackendError: 'wine --version' exited with code {result.returncode}.\n"
                f"stderr: {result.stderr.strip()}\n"
                "Wine is installed but appears broken. Try reinstalling Wine."
            )

    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains Backend.WINE_DBPOWERAMP."""
        return Backend.WINE_DBPOWERAMP in preset.backends

    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion via CoreConverter.exe under Wine.

        Translates Linux paths to Windows paths using winepath, then runs
        CoreConverter with the appropriate encoder and arguments.

        Args:
            job: The conversion job to execute.
            stream_callback: If not None, called once per stdout/stderr line.

        Returns:
            JobResult with status=SUCCESS if the process exited 0, otherwise FAILED.
        """
        wine_binary = self._wine_cfg.wine_binary
        wine_prefix_str = str(self._wine_cfg.wine_prefix)
        winepath_binary = self._wine_cfg.winepath_binary
        coreconverter_path = self._wine_cfg.coreconverter_path

        # Translate paths via winepath
        wine_infile = to_wine_path(job.infile, wine_binary, wine_prefix_str, winepath_binary)
        wine_outfile = to_wine_path(job.outfile, wine_binary, wine_prefix_str, winepath_binary)

        # Get backend args from preset
        backend_args = job.preset.backends[Backend.WINE_DBPOWERAMP]
        encoder = backend_args.encoder or ""
        extra_args = list(backend_args.args)

        # Build command: wine CoreConverter.exe -infile=... -outfile=... -convert_to=...
        # Same quoting rule as the native backend: CoreConverter uses its own
        # argument parser rather than CommandLineToArgvW rules and splits on
        # whitespace. We pass the command line as a single pre-formatted string
        # (shell=False) so wine forwards it verbatim to CoreConverter.exe.
        # If a stripped extra arg contains whitespace it must be re-wrapped
        # in literal double quotes, otherwise CreateProcessW (which Wine
        # ultimately drives on Windows) will tokenise it on the space — e.g.
        # -codec="LC AAC" without the wrapper becomes -codec=LC and the
        # orphan "AAC" silently breaks the QAAC invocation.
        def _quote_extra(arg: str) -> str:
            stripped = arg.replace('"', "")
            return f'"{stripped}"' if any(c.isspace() for c in stripped) else stripped
        safe_extra_args = [_quote_extra(a) for a in extra_args]
        cmd = (
            f'"{wine_binary}" "{coreconverter_path}" '
            f'-infile="{wine_infile}" '
            f'-outfile="{wine_outfile}" '
            f'-convert_to="{encoder}" '
            + " ".join(safe_extra_args)
        )  # fmt: skip

        # Build environment with WINEPREFIX
        env: dict[str, str] = {**os.environ, "WINEPREFIX": wine_prefix_str}

        stdout_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            bufsize=1,
            env=env,
        )

        assert proc.stdout is not None  # type guard

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            stdout_lines.append(line)
            if stream_callback is not None:
                stream_callback(line)

        proc.stdout.close()
        exit_code = proc.wait()

        stdout_text = "".join(stdout_lines)
        if exit_code == 0:
            return JobResult(job=job, status="SUCCESS", stdout=stdout_text)
        else:
            return JobResult(
                job=job,
                status="FAILED",
                error_msg=f"CoreConverter exited with code {exit_code}",
                stdout=stdout_text,
            )
