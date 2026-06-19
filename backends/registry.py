"""backends/registry.py: Factory for ConversionBackend instances with fail-fast environment validation."""

from backends.native_ffmpeg import NativeFfmpegBackend
from backends.wine_dbpoweramp import WineDbpowerampBackend
from config.settings_loader import Settings
from exceptions import BackendError, ConfigError
from models.types import Backend


class UnknownBackendError(ConfigError):
    """Raised when a backend name is not recognised or not configured."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown or unrecognised backend: {name}")


def resolve_backend_for_run(cli_backend: Backend | None, settings: Settings) -> Backend:
    """Return the Backend to use for this run.

    Args:
        cli_backend:  Backend explicitly requested via CLI (may be None).
        settings:     Application settings.

    Returns:
        cli_backend if it is not None, otherwise the backend.default from settings.yaml.
    """
    if cli_backend is not None:
        return cli_backend

    default_str = settings.backend.default
    try:
        return Backend(default_str)
    except ValueError:
        raise UnknownBackendError(default_str)


def get_backend(name: Backend, settings: Settings) -> "ConversionBackend":
    """Instantiate and return the requested ConversionBackend.

    Validates the backend environment immediately on instantiation (fail-fast —
    before any file discovery or conversion work begins).

    Args:
        name:    Which backend to instantiate.
        settings: Application settings.

    Returns:
        An instantiated ConversionBackend subclass.

    Raises:
        UnknownBackendError: If name is not a recognised Backend enum value.
        BackendError:       If the backend's environment is invalid (e.g. prefix
                            missing for wine, binary not found for native).
    """
    from backends.base import ConversionBackend

    backend: ConversionBackend

    if name == Backend.NATIVE_FFMPEG:
        backend = NativeFfmpegBackend(settings)
    elif name == Backend.WINE_DBPOWERAMP:
        backend = WineDbpowerampBackend(settings)
    else:
        raise UnknownBackendError(name.value if isinstance(name, Backend) else str(name))

    # Fail-fast: validate environment immediately, before returning.
    backend.validate_environment()

    return backend
