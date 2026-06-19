"""models/types.py: Pure dataclass/enum types — dependency root, no I/O."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal, Optional


class Backend(str, Enum):
    """Conversion backend: wine_dbpoweramp or native_ffmpeg."""

    WINE_DBPOWERAMP = "wine_dbpoweramp"
    NATIVE_FFMPEG = "native_ffmpeg"


class LossyAction(str, Enum):
    """Action to take on lossy source files: leave (skip), copy, or convert."""

    LEAVE = "leave"
    COPY = "copy"
    CONVERT = "convert"


JobType = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]


@dataclass
class SidecarPolicy:
    """Sidecar (lyrics/text) file copy policy."""

    copy: bool = False
    extensions: list[str] = field(default_factory=list)
    hide: bool = False


@dataclass
class CoverPolicy:
    """Cover image file copy policy."""

    copy: bool = False
    patterns: list[str] = field(default_factory=list)
    hide: bool = False


@dataclass
class BackendPresetArgs:
    """Per-backend encoder identity and arguments for a preset."""

    encoder: Optional[str] = None
    tool: Optional[str] = None
    args: list[str] = field(default_factory=list)
    requires_encoder: Optional[str] = None


@dataclass
class PresetConfig:
    """Full encoding preset: output format, per-backend args, and sidecar policy."""

    name: str
    ext: str
    backends: dict[Backend, BackendPresetArgs]
    lyrics: Optional[SidecarPolicy] = None
    covers: Optional[CoverPolicy] = None


@dataclass
class ConversionJob:
    """A single file to be processed: convert, copy, or skip."""

    infile: Path
    outfile: Path
    preset: PresetConfig
    job_type: JobType
    is_lossy_source: Optional[bool] = None
    reason: Optional[str] = None


@dataclass
class JobResult:
    """Result of a ConversionJob: status, optional error, and stdout capture."""

    job: ConversionJob
    status: JobStatus
    error_msg: Optional[str] = None
    stdout: Optional[str] = None
