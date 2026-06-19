"""config/settings_loader.py: Load and validate settings.yaml into a Settings dataclass."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from exceptions import ConfigError


# ---------------------------------------------------------------------------
# Sub-dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WineBackendConfig:
    """Wine dBpoweramp backend: wine binary, prefix, CoreConverter path, winepath."""

    wine_binary: str
    wine_prefix: Path
    coreconverter_path: str
    winepath_binary: str


@dataclass
class NativeBackendConfig:
    """Native ffmpeg backend: paths to ffmpeg, flac, lame, opusenc binaries."""

    ffmpeg_binary: str
    flac_binary: str
    lame_binary: str
    opusenc_binary: str


@dataclass
class BackendConfig:
    """Combined backend config: default plus per-backend sub-configs."""

    default: str
    wine_dbpoweramp: WineBackendConfig
    native_ffmpeg: NativeBackendConfig


@dataclass
class ToolsConfig:
    """Tool binary paths: ffprobe."""

    ffprobe_binary: str


@dataclass
class HistoryConfig:
    """History database settings."""

    db_path: str


@dataclass
class ExecutionConfig:
    """Execution pool settings: worker count and model."""

    default_workers: int
    probe_workers: int
    worker_model: str


@dataclass
class LoggingConfig:
    """Logging level: DEBUG | INFO | WARNING | ERROR."""

    level: str


@dataclass
class Settings:
    """Top-level settings: backend defaults, tool paths, history, execution, logging."""

    backend: BackendConfig
    tools: ToolsConfig
    history: HistoryConfig
    execution: ExecutionConfig
    logging: LoggingConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_BACKENDS = {"wine_dbpoweramp", "native_ffmpeg"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_VALID_WORKER_MODELS = {"thread", "process"}


def _raise(msg: str) -> None:
    raise ConfigError(msg)


def _get(data: dict[str, Any], key: str, path: str) -> Any:
    try:
        return data[key]
    except KeyError:
        _raise(f"Missing required key '{path}' in settings.yaml")


def _str(data: dict[str, Any], key: str, path: str, allow_empty: bool = True) -> str:
    val = _get(data, key, path)
    if not isinstance(val, str):
        _raise(f"'{path}' must be a string, got {type(val).__name__}")
    if not allow_empty and not val:
        _raise(f"'{path}' must be a non-empty string")
    return val


def _int(data: dict[str, Any], key: str, path: str, min_val: int = 1) -> int:
    val = _get(data, key, path)
    if not isinstance(val, int) or isinstance(val, bool):
        _raise(f"'{path}' must be an integer, got {type(val).__name__}")
    if val < min_val:
        _raise(f"'{path}' must be >= {min_val}, got {val}")
    return val


def _str_enum(data: dict[str, Any], key: str, path: str, valid: set[str]) -> str:
    val = _str(data, key, path, allow_empty=False)
    if val not in valid:
        _raise(f"'{path}' must be one of {sorted(valid)}, got '{val}'")
    return val


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_settings(path: Path | str) -> Settings:
    """Parse and validate settings.yaml. Raises ConfigError on any malformed or invalid config."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        _raise(f"Failed to parse settings.yaml: {e}")
    if not isinstance(raw, dict):
        _raise("settings.yaml must contain a YAML mapping at the top level")

    data = raw

    # -- backend --
    backend_data = _get(data, "backend", "backend")

    default = _str_enum(backend_data, "default", "backend.default", _VALID_BACKENDS)

    wd = _get(backend_data, "wine_dbpoweramp", "backend.wine_dbpoweramp")
    wine_dbpoweramp = WineBackendConfig(
        wine_binary=_str(wd, "wine_binary", "backend.wine_dbpoweramp.wine_binary", allow_empty=False),
        wine_prefix=Path(_str(wd, "wine_prefix", "backend.wine_dbpoweramp.wine_prefix", allow_empty=False)).expanduser(),
        coreconverter_path=_str(wd, "coreconverter_path", "backend.wine_dbpoweramp.coreconverter_path", allow_empty=False),
        winepath_binary=_str(wd, "winepath_binary", "backend.wine_dbpoweramp.winepath_binary", allow_empty=False),
    )

    nf = _get(backend_data, "native_ffmpeg", "backend.native_ffmpeg")
    native_ffmpeg = NativeBackendConfig(
        ffmpeg_binary=_str(nf, "ffmpeg_binary", "backend.native_ffmpeg.ffmpeg_binary", allow_empty=False),
        flac_binary=_str(nf, "flac_binary", "backend.native_ffmpeg.flac_binary", allow_empty=False),
        lame_binary=_str(nf, "lame_binary", "backend.native_ffmpeg.lame_binary", allow_empty=False),
        opusenc_binary=_str(nf, "opusenc_binary", "backend.native_ffmpeg.opusenc_binary", allow_empty=False),
    )

    backend = BackendConfig(
        default=default,
        wine_dbpoweramp=wine_dbpoweramp,
        native_ffmpeg=native_ffmpeg,
    )

    # -- tools --
    tools_data = _get(data, "tools", "tools")
    tools = ToolsConfig(
        ffprobe_binary=_str(tools_data, "ffprobe_binary", "tools.ffprobe_binary", allow_empty=False),
    )

    # -- history --
    history_data = _get(data, "history", "history")
    history = HistoryConfig(
        db_path=_str(history_data, "db_path", "history.db_path", allow_empty=False),
    )

    # -- execution --
    exec_data = _get(data, "execution", "execution")
    execution = ExecutionConfig(
        default_workers=_int(exec_data, "default_workers", "execution.default_workers"),
        probe_workers=_int(exec_data, "probe_workers", "execution.probe_workers"),
        worker_model=_str_enum(exec_data, "worker_model", "execution.worker_model", _VALID_WORKER_MODELS),
    )

    # -- logging --
    logging_data = _get(data, "logging", "logging")
    logging = LoggingConfig(
        level=_str_enum(logging_data, "level", "logging.level", _VALID_LOG_LEVELS),
    )

    return Settings(
        backend=backend,
        tools=tools,
        history=history,
        execution=execution,
        logging=logging,
    )
