"""backends/registry.py: Factory for ConversionBackend instances with fail-fast environment validation."""

from src.backends.native_dbpoweramp import NativeDbpowerampBackend
from src.backends.native_ffmpeg import NativeFfmpegBackend
from src.backends.wine_dbpoweramp import WineDbpowerampBackend
from src.config.settings_loader import Settings
from src.exceptions import BackendError, ConfigError
from src.models.types import Backend


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


def detect_backend_for_run(
    cli_backend: Backend | None,
    settings: Settings,
    preset: "PresetConfig",
    platform: str,
    auto_detect_override: bool | None = None,
) -> Backend:
    """Resolve the effective Backend for a run using the following priority:

    1. If ``cli_backend`` is not None, return it immediately (CLI wins).
    2. Resolve ``auto_detect`` — use ``auto_detect_override`` if provided,
       otherwise fall back to ``settings.backend.auto_detect``.
    3. If ``auto_detect`` is True **and** the platform is ``"win32"``
       **and** ``Backend.NATIVE_DBPOWERAMP`` is in ``preset.backends``,
       return ``Backend.NATIVE_DBPOWERAMP``.
    4. Otherwise delegate to :func:`resolve_backend_for_run`.
    """
    if cli_backend is not None:
        return cli_backend

    auto_detect = (
        auto_detect_override
        if auto_detect_override is not None
        else settings.backend.auto_detect
    )

    if (
        auto_detect
        and platform == "win32"
        and Backend.NATIVE_DBPOWERAMP in preset.backends
    ):
        return Backend.NATIVE_DBPOWERAMP

    return resolve_backend_for_run(None, settings)


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
    from src.backends.base import ConversionBackend

    backend: ConversionBackend

    if name == Backend.NATIVE_FFMPEG:
        backend = NativeFfmpegBackend(settings)
    elif name == Backend.WINE_DBPOWERAMP:
        backend = WineDbpowerampBackend(settings)
    elif name == Backend.NATIVE_DBPOWERAMP:
        backend = NativeDbpowerampBackend(settings)
    else:
        raise UnknownBackendError(name.value if isinstance(name, Backend) else str(name))

    # Fail-fast: validate environment immediately, before returning.
    backend.validate_environment()

    return backend
