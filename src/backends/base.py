"""backends/base.py: Abstract base class for all conversion backends."""

from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.models.types import Backend, ConversionJob, JobResult, PresetConfig


class ConversionBackend(ABC):
    """Abstract base class for audio conversion backends.

    Subclasses must implement all four abstract methods. Instances are
    long-lived within a single run; environment validation happens once at
    instantiation time via `validate_environment()`.
    """

    @abstractmethod
    def name(self) -> Backend:
        """Return the backend identifier."""

    @abstractmethod
    def validate_environment(self) -> None:
        """Check that required binaries/paths/prefix exist.

        Raises BackendError with a human-readable, fix-it message if
        validation fails (e.g. binary not found, prefix missing).
        """

    @abstractmethod
    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains this backend's key."""

    @abstractmethod
    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion and return a JobResult.

        Args:
            job: The conversion job to execute.
            stream_callback: If not None, called once per stdout/stderr line
                from the transcoder process (mirrors the original script's
                verbose_queue streaming behaviour).

        Returns:
            JobResult with status=SUCCESS if the process exited 0, otherwise
            status=FAILED with error_msg and stdout populated.
        """
