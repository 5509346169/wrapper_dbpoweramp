"""backends/native_dbpoweramp.py: Native dBpoweramp CoreConverter conversion backend."""

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from backends.base import ConversionBackend
from config.settings_loader import Settings
from exceptions import BackendError
from models.types import (
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

        cmd = [
            coreconverter_path,
            f"-infile={str(job.infile)}",
            f"-outfile={str(job.outfile)}",
            f"-convert_to={encoder}",
            *extra_args,
        ]

        stdout_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
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
