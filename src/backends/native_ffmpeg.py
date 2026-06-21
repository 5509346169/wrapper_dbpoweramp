"""backends/native_ffmpeg.py: Native ffmpeg-based conversion backend."""

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable

from src.exceptions import BackendError
from src.models.types import (
    Backend,
    BackendPresetArgs,
    ConversionJob,
    JobResult,
    PresetConfig,
)
from src.config.settings_loader import Settings


# Cached output of `ffmpeg -encoders`, populated once per process lifetime.
_ffmpeg_encoders_cache: Optional[str] = None


def _get_encoders_output(ffmpeg_binary: str) -> str:
    """Return ffmpeg -encoders stdout, caching across calls within the same process."""
    global _ffmpeg_encoders_cache  # noqa: PLW0603
    if _ffmpeg_encoders_cache is None:
        result = subprocess.run(
            [ffmpeg_binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            shell=False,
        )
        _ffmpeg_encoders_cache = result.stdout
    return _ffmpeg_encoders_cache


class NativeFfmpegBackend:
    """Conversion backend that shells out to ffmpeg (or a compatible standalone tool)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ffmpeg_binary = settings.backend.native_ffmpeg.ffmpeg_binary
        self._flac_binary = settings.backend.native_ffmpeg.flac_binary
        self._lame_binary = settings.backend.native_ffmpeg.lame_binary
        self._opusenc_binary = settings.backend.native_ffmpeg.opusenc_binary

    def name(self) -> Backend:
        """Return the backend identifier."""
        return Backend.NATIVE_FFMPEG

    def validate_environment(self) -> None:
        """Verify ffmpeg_binary resolves to an existing executable."""
        binary = self._ffmpeg_binary
        resolved = shutil.which(binary)
        if resolved is None:
            # Check if it's an absolute path that exists
            p = Path(binary)
            if not p.is_absolute() or not p.is_file():
                raise BackendError(
                    f"ffmpeg binary '{binary}' not found on PATH and is not an absolute path to an existing file.\n"
                    "Install ffmpeg with: sudo pacman -S ffmpeg  (Arch/CachyOS)\n"
                    "or: sudo apt install ffmpeg          (Debian/Ubuntu)\n"
                    "or: sudo dnf install ffmpeg          (Fedora)"
                )

    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains Backend.NATIVE_FFMPEG."""
        return Backend.NATIVE_FFMPEG in preset.backends

    def _check_encoder(self, encoder_name: str) -> None:
        """Raise BackendError if encoder_name is not listed in ffmpeg -encoders output."""
        output = _get_encoders_output(self._ffmpeg_binary)
        # Encoders are listed as e.g. " A.... libfdk_aac   " so check the short code token.
        # The short codec code is always the first word on the line; scan for it.
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith(encoder_name) or f" {encoder_name} " in line:
                return
        raise BackendError(
            f"Encoder '{encoder_name}' is not available in this ffmpeg build.\n"
            "The ffmpeg binary being used does not include this encoder.\n"
            "On CachyOS/Arch, install a full-featured ffmpeg build:\n"
            "  sudo pacman -S ffmpeg-full    # from AUR, includes libfdk_aac and others\n"
            "Or rebuild your ffmpeg preset without this encoder (remove it from your\n"
            "presets.yaml aac-vbr-high entry's requires_encoder field)."
        )

    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion via ffmpeg (or standalone tool) and return a JobResult.

        Args:
            job: The conversion job to execute.
            stream_callback: If not None, called once per stdout/stderr line.

        Returns:
            JobResult with status=SUCCESS if the process exited 0, otherwise FAILED.
        """
        backend_args = job.preset.backends[Backend.NATIVE_FFMPEG]

        # -- requires_encoder gate --
        if backend_args.requires_encoder:
            self._check_encoder(backend_args.requires_encoder)

        # -- build command --
        tool = backend_args.tool or "ffmpeg"
        preset_args = list(backend_args.args)

        if tool == "ffmpeg":
            cmd = [
                self._ffmpeg_binary,
                "-y",
                "-i",
                str(job.infile),
                *preset_args,
                str(job.outfile),
            ]
        else:
            # Standalone tool: look up binary from settings, args come before infile/outfile.
            tool_binary_map = {
                "flac": self._flac_binary,
                "lame": self._lame_binary,
                "opusenc": self._opusenc_binary,
            }
            tool_binary = tool_binary_map.get(tool)
            if tool_binary is None:
                raise BackendError(
                    f"Unknown standalone tool '{tool}' in preset '{job.preset.name}'. "
                    f"Supported tools: ffmpeg, flac, lame, opusenc"
                )
            cmd = [tool_binary, *preset_args, str(job.infile), str(job.outfile)]

        # -- run, streaming output line-by-line --
        stdout_lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
            bufsize=1,
        )

        assert proc.stdout is not None  # mypy guard for the type of proc.stdout

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            stdout_lines.append(line)
            if stream_callback is not None:
                stream_callback(line)

        proc.stdout.close()
        exit_code = proc.wait()

        if exit_code == 0:
            return JobResult(
                job=job,
                status="SUCCESS",
                stdout="".join(stdout_lines),
            )
        else:
            return JobResult(
                job=job,
                status="FAILED",
                error_msg=f"ffmpeg exited with code {exit_code}",
                stdout="".join(stdout_lines),
            )
