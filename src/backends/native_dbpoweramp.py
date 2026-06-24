"""backends/native_dbpoweramp.py: Native dBpoweramp CoreConverter conversion backend."""

import os
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


class NativeDbpowerampBackend(ConversionBackend):
    """Conversion backend that runs dBpoweramp's CoreConverter.exe natively (no Wine)."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the native dBpoweramp backend.

        Args:
            settings: Application settings containing backend.native_dbpoweramp config.
        """
        self._settings = settings
        self._cfg = settings.backend.native_dbpoweramp

    def name(self) -> Backend:
        """Return the backend identifier."""
        return Backend.NATIVE_DBPOWERAMP

    def validate_environment(self) -> None:
        """Check that coreconverter_path exists and is a file.

        Raises BackendError with a human-readable, fix-it message if the check fails.
        """
        coreconverter_path = Path(self._cfg.coreconverter_path)
        if not coreconverter_path.is_file():
            raise BackendError(
                f"BackendError: CoreConverter not found at '{coreconverter_path}'.\n"
                "Install dBpoweramp or update the coreconverter_path in settings.yaml:\n"
                "  backend:\n"
                "    native_dbpoweramp:\n"
                "      coreconverter_path: 'C:\\Program Files\\dBpoweramp\\CoreConverter.exe'"
            )

    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains Backend.NATIVE_DBPOWERAMP."""
        return Backend.NATIVE_DBPOWERAMP in preset.backends

    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion via CoreConverter.exe natively.

        Args:
            job: The conversion job to execute.
            stream_callback: If not None, called once per stdout/stderr line.

        Returns:
            JobResult with status=SUCCESS if the process exited 0, otherwise FAILED.
        """
        coreconverter_path = self._cfg.coreconverter_path

        backend_args = job.preset.backends[Backend.NATIVE_DBPOWERAMP]
        encoder = backend_args.encoder or ""
        extra_args = list(backend_args.args)

        # CoreConverter uses its own argument parser rather than the standard
        # Windows CommandLineToArgvW rules. It splits the raw command line on
        # whitespace and then strips a single pair of surrounding double quotes
        # from each token. That means:
        #   1. Each argument containing spaces must be wrapped in literal double
        #      quotes *in the raw command-line string* (e.g. -infile="C:\Users\... 10\...").
        #   2. Python's subprocess.list2cmdline escapes any embedded " with a
        #      backslash (\"), so we cannot pass a list of args — we'd end up with
        #      \"...\" on the wire and CoreConverter would parse the backslash as
        #      part of the path ("Audio Source: \"C:\Users\Windows...").
        #
        # The fix is to build the command line as a single pre-formatted string
        # and pass it to subprocess.Popen with shell=False. On Windows that
        # bypasses list2cmdline and the string is handed verbatim to
        # CreateProcessW, where CoreConverter's parser handles it correctly.
        #
        # extra_args come from presets.yaml and may contain embedded quotes
        # (e.g. -encoding="SLOW"); we strip those, since CoreConverter treats
        # them as value terminators and the embedded quotes in our preset
        # flags are decorative wrappers (e.g. SLOW → SLOW).
        safe_extra_args = [a.replace('"', "") for a in extra_args]  # fmt: skip
        cmd = (
            f'"{coreconverter_path}" '
            f'-infile="{job.infile}" '
            f'-outfile="{job.outfile}" '
            f'-convert_to="{encoder}" '
            + " ".join(safe_extra_args)
        )  # fmt: skip

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
            env=os.environ,
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
