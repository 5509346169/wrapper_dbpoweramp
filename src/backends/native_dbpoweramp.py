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
from src.pathing.long_path import stage_paths, unstage


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

        # Long-path workaround: on Windows, CoreConverter and its child
        # encoders (qaac.exe, lame.exe, etc.) call CreateFileW without the
        # ``\\?\`` prefix, so they fail to open any source/destination path
        # whose absolute form exceeds MAX_PATH (260 chars). When the
        # user opts in via ``long_paths: true`` (settings.yaml) or
        # ``--long-paths`` (CLI), we resolve both paths to their 8.3 short
        # names, run CoreConverter against the short paths, and rename the
        # result back to the original long destination on success.
        # See ``src.pathing.long_path`` for the gory details.
        staged = stage_paths(
            infile=job.infile,
            outfile=job.outfile,
            enabled=self._cfg.long_paths,
        )
        infile_for_cmd = staged.infile
        outfile_for_cmd = staged.outfile

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
        #
        # If the resulting value contains whitespace, it MUST be re-wrapped in
        # literal double quotes — otherwise CreateProcessW will split it into
        # multiple tokens and the trailing fragment will be treated as a
        # separate (and unknown) argument, which is why e.g. qaac-cvbr-256's
        # -codec="LC AAC" silently produced a 0-byte file.
        def _quote_extra(arg: str) -> str:
            stripped = arg.replace('"', "")
            return f'"{stripped}"' if any(c.isspace() for c in stripped) else stripped
        safe_extra_args = [_quote_extra(a) for a in extra_args]  # fmt: skip
        cmd = (
            f'"{coreconverter_path}" '
            f'-infile="{infile_for_cmd}" '
            f'-outfile="{outfile_for_cmd}" '
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

        if exit_code == 0 and staged.staged:
            # On NTFS, the short path is just an alias for the same physical
            # file as the long path — CoreConverter's write is already visible
            # at the long destination. ``unstage()`` only checks that the
            # long-path output now exists and is non-empty. If not, it means
            # CoreConverter exited 0 but didn't actually write anything
            # (extremely rare; usually a permissions issue or read-only
            # output volume).
            if not unstage(staged):
                return JobResult(
                    job=job,
                    status="FAILED",
                    error_msg=(
                        f"CoreConverter exited 0 but the expected output at "
                        f"{staged.long_outfile} is missing or empty. "
                        "Check that the destination's parent directory is "
                        "writable and not full."
                    ),
                    stdout=stdout_text,
                )
            # The on-disk file is now at job.outfile (the long path), which
            # is where the runner's post-write verifier expects it.

        if exit_code == 0:
            return JobResult(job=job, status="SUCCESS", stdout=stdout_text)
        else:
            return JobResult(
                job=job,
                status="FAILED",
                error_msg=f"CoreConverter exited with code {exit_code}",
                stdout=stdout_text,
            )
