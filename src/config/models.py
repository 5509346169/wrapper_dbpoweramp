"""config/models.py: Dataclasses describing the structure of settings.yaml."""

from dataclasses import dataclass
from pathlib import Path


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
class NativeDbpowerampConfig:
    """Native dBpoweramp backend: path to CoreConverter.exe on Windows."""

    coreconverter_path: str


@dataclass
class BackendConfig:
    """Combined backend config: default plus per-backend sub-configs."""

    default: str
    auto_detect: bool
    wine_dbpoweramp: WineBackendConfig
    native_dbpoweramp: NativeDbpowerampConfig
    native_ffmpeg: NativeBackendConfig


@dataclass
class ToolsConfig:
    """Tool binary paths (mutagen requires no external binary)."""

    pass  # empty for now; kept for future tool paths


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
