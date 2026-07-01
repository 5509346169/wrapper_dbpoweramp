"""ui/progress/verbose_sink.py: VerboseProgressSink — prints file-level details to stdout."""

from rich.console import Console

from src.ui.progress.protocol import SubtaskID


class VerboseProgressSink:
    """
    A ProgressSink that prints file-level details to stdout for verbose mode.

    Used during --build-index when -v/--verbose is enabled.
    """

    def __init__(self) -> None:
        self._console = Console(force_terminal=True, legacy_windows=False)

    def start_phase(self, name: str, total: int) -> None:
        pass

    def advance(self, amount: int = 1) -> None:
        pass

    def start_subtask(self, name: str) -> SubtaskID:
        return SubtaskID(-1)

    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        pass

    def log(self, message: str) -> None:
        pass

    def stop(self) -> None:
        pass

    def stop_phase(self) -> None:
        pass

    def set_activity(self, activity: str) -> None:
        pass

    def log_file(self, message: str) -> None:
        """Print verbose file-level information to stdout, interpreting Rich markup."""
        self._console.print(message)

    def log_phase(self, name: str) -> None:
        """Print phase header to stdout."""
        self._console.print(f"[{name}]")

    def set_phase_label(self, label: str) -> None:
        """Verbose sink: print the new tier label as a header."""
        self._console.print(f"[{label}]")

    def set_counters(self, demoted: int = 0, kept: int = 0) -> None:
        """Verbose sink: counters are not applicable (output goes to stdout)."""
        pass

    def log_result(self, filename: str, job_type: str, is_lossy: bool | None = None) -> None:
        """Print file processing result to stdout."""
        lossy_marker = " [LOSSY]" if is_lossy else ""
        self._console.print(f"  {filename} -> {job_type}{lossy_marker}")

    def log_verify_result(self, infile: str, status: str, reason: str | None,
                         fmt: str | None, duration_s: float | None) -> None:
        """Print a verify result line to stdout.

        Format: verify   Okay   3.42s   FLAC/PCM_16   /path/to/out.flac
        """
        dur_str = f"{duration_s:.2f}s" if duration_s is not None else "?"
        fmt_str = fmt or "?"
        if status == "OK":
            self._console.print(f"verify   Okay   {dur_str}   {fmt_str}   {infile}")
        elif status == "UNSUPPORTED":
            self._console.print(f"verify   Skipped - {reason or 'unsupported format'}   {infile}")
        else:
            self._console.print(f"verify   Not - {reason or 'unknown reason'}   {infile}")

    def log_convert_result(self, infile: str, outfile: str, encoder: str,
                          output_bytes: int | None, elapsed_s: float,
                          status: str, error_msg: str | None = None) -> None:
        """Print a conversion result line to stdout.

        Format: convert  SUCCESS  12.34s  47.2 MiB  FLAC -> ALAC  /path/to/out.m4a
                convert  FAILED   12.34s        -  FLAC -> ALAC  /path/to/out.m4a  (reason)
        """
        import os
        elapsed_str = f"{elapsed_s:.2f}s"

        if status == "SUCCESS":
            if output_bytes is not None:
                if output_bytes >= 1 << 30:
                    size_str = f"{output_bytes / (1 << 30):.1f} GiB"
                elif output_bytes >= 1 << 20:
                    size_str = f"{output_bytes / (1 << 20):.1f} MiB"
                elif output_bytes >= 1 << 10:
                    size_str = f"{output_bytes / (1 << 10):.1f} KiB"
                else:
                    size_str = f"{output_bytes} B"
            else:
                size_str = "?"
            self._console.print(
                f"convert  SUCCESS  {elapsed_str}  {size_str:>9}  {encoder}  {outfile}"
            )
        else:
            reason = f"  ({error_msg})" if error_msg else ""
            self._console.print(
                f"convert  FAILED   {elapsed_str}         -  {encoder}  {outfile}{reason}"
            )
