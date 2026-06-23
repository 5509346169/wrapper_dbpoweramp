"""exceptions.py: Project-wide custom exceptions for configuration loading."""


class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or fails validation."""
    pass


class PresetNotFoundError(Exception):
    """Raised when a requested preset name is not found in the loaded presets."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        joined = ", ".join(sorted(available))
        super().__init__(f"Preset '{name}' not found. Available presets: {joined}")


class ProbeError(Exception):
    """Raised when audio metadata extraction fails (mutagen)."""

    def __init__(self, file: str, stderr: str) -> None:
        self.file = file
        self.stderr = stderr
        super().__init__(f"failed to probe {file}: {stderr}")


class PathConfigError(Exception):
    """Raised when a path configuration is invalid (e.g., source_path not an ancestor of input_path)."""
    pass


class BackendError(Exception):
    """Raised when a backend (e.g., Wine) fails or is misconfigured."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class IndexError(Exception):
    """Raised when the temporary index database cannot be created, opened, or written."""
    pass
