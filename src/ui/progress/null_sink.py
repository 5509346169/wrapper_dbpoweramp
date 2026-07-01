"""ui/progress/null_sink.py: NullProgressSink — no-op sink for verbose mode where output goes directly to stdout."""

from src.ui.progress.protocol import SubtaskID


class NullProgressSink:
    """
    A no-op ProgressSink for verbose mode where output goes directly to stdout.

    All methods are no-ops - verbose output is printed directly via stream_callback.
    """

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

    def log_file(self, message: str) -> None:
        """No-op mirror of RichProgressSink.log_file. The verbose mode never
        renders a master bar so per-decision file logs are silent here.
        """
        pass

    def stop(self) -> None:
        pass

    def stop_phase(self) -> None:
        pass

    def set_activity(self, activity: str) -> None:
        pass

    def set_phase_label(self, label: str) -> None:
        pass

    def set_counters(self, demoted: int = 0, kept: int = 0) -> None:
        pass

    def log_verify_result(self, infile: str, status: str, reason: str | None,
                         fmt: str | None, duration_s: float | None) -> None:
        pass
