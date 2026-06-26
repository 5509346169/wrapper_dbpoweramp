# Module Reference

This document provides detailed reference for each module in the `src/` package.

---

## Package Structure

```
src/
├── __init__.py
├── exceptions.py           # Custom exception classes
├── audio/
│   ├── __init__.py
│   └── inspector.py       # Multi-tier lossy detection
├── backends/
│   ├── __init__.py
│   ├── base.py           # ConversionBackend ABC
│   ├── registry.py       # Backend factory
│   ├── native_ffmpeg.py  # FFmpeg backend
│   ├── native_dbpoweramp.py  # Native dBpoweramp backend
│   └── wine_dbpoweramp.py    # Wine dBpoweramp backend
├── cli/
│   ├── __init__.py
│   └── args.py           # Argument parsing
├── config/
│   ├── __init__.py
│   ├── settings_loader.py    # settings.yaml loader
│   └── preset_loader.py     # presets.yaml loader
├── execution/
│   ├── __init__.py
│   ├── runner.py         # Job execution (main entry)
│   ├── run_all.py        # Top-level pool orchestrator
│   ├── run_job.py        # Single-job execution
│   ├── event_drain.py    # UI event draining
│   └── events.py         # Event queue construction
├── history/
│   ├── __init__.py
│   ├── conversion_db.py   # Synchronous history wrapper
│   ├── write_queue.py    # Async writer thread
│   └── schema.py         # Shared schema and pragmas
├── index/
│   ├── __init__.py
│   ├── scanner.py        # File scanning
│   ├── builder.py       # Index DB manager
│   ├── cleanup.py        # Index cleanup
│   └── scan_cache.py     # Scan cache for probe optimization
├── jobs/
│   ├── __init__.py
│   ├── builder.py        # Job list building
│   ├── enrich.py         # Stream-probe for lossy detection
│   └── classify.py      # Job type classification
├── models/
│   ├── __init__.py
│   └── types.py          # Dataclass types
├── pathing/
│   ├── __init__.py
│   └── resolver.py       # Path resolution
├── sidecars/
│   ├── __init__.py
│   └── manager.py        # Sidecar file copying
└── ui/
    ├── __init__.py
    ├── progress_view.py  # Progress sink exports
    └── progress/
        ├── __init__.py
        ├── protocol.py   # ProgressSink protocol
        ├── renderer.py   # Progress bar renderer
        └── rich_sink.py  # Rich progress implementation
```

---

## `src/exceptions.py`

Custom exception classes for the application.

### Classes

#### `ConfigError`

Raised when a configuration file is missing, malformed, or fails validation.

```python
class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or fails validation."""
    pass
```

#### `PresetNotFoundError`

Raised when a requested preset name is not found in the loaded presets.

```python
class PresetNotFoundError(Exception):
    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        joined = ", ".join(sorted(available))
        super().__init__(f"Preset '{name}' not found. Available presets: {joined}")
```

#### `ProbeError`

Raised when audio metadata extraction fails (mutagen).

```python
class ProbeError(Exception):
    def __init__(self, file: str, stderr: str) -> None:
        self.file = file
        self.stderr = stderr
        super().__init__(f"failed to probe {file}: {stderr}")
```

#### `PathConfigError`

Raised when a path configuration is invalid.

```python
class PathConfigError(Exception):
    pass
```

#### `BackendError`

Raised when a backend (e.g., Wine) fails or is misconfigured.

```python
class BackendError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
```

#### `IndexError`

Raised when the temporary index database cannot be created, opened, or written.

```python
class IndexError(Exception):
    pass
```

---

## `src/models/types.py`

Pure dataclass and enum types - no I/O operations.

### Enums

#### `Backend`

Conversion backend identifiers.

```python
class Backend(str, Enum):
    WINE_DBPOWERAMP = "wine_dbpoweramp"
    NATIVE_DBPOWERAMP = "native_dbpoweramp"
    NATIVE_FFMPEG = "native_ffmpeg"
```

#### `LossyAction`

Action to take on lossy source files.

```python
class LossyAction(str, Enum):
    LEAVE = "leave"     # Skip lossy files
    COPY = "copy"       # Copy as-is
    CONVERT = "convert" # Transcode
```

### Type Aliases

```python
JobType = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
```

### Constants

```python
AUDIO_EXTENSIONS: set[str] = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".ape", ".wv", ".tta"}
```

### Dataclasses

#### `SidecarPolicy`

Sidecar (lyrics/text) file copy policy.

```python
@dataclass
class SidecarPolicy:
    copy: bool = False
    extensions: list[str] = field(default_factory=list)
    hide: bool = False
```

#### `CoverPolicy`

Cover image file copy policy.

```python
@dataclass
class CoverPolicy:
    copy: bool = False
    patterns: list[str] = field(default_factory=list)
    hide: bool = False
```

#### `BackendPresetArgs`

Per-backend encoder identity and arguments for a preset.

```python
@dataclass
class BackendPresetArgs:
    encoder: Optional[str] = None          # dBpoweramp encoder name
    tool: Optional[str] = None             # FFmpeg tool (ffmpeg, flac, etc.)
    args: list[str] = field(default_factory=list)
    requires_encoder: Optional[str] = None  # Encoder to check in ffmpeg -encoders
```

#### `PresetConfig`

Full encoding preset definition.

```python
@dataclass
class PresetConfig:
    name: str
    ext: str                               # Output extension (.flac, .mp3, etc.)
    backends: dict[Backend, BackendPresetArgs]
    lyrics: Optional[SidecarPolicy] = None
    covers: Optional[CoverPolicy] = None
```

#### `ConversionJob`

A single file to be processed.

```python
@dataclass
class ConversionJob:
    infile: Path
    outfile: Path
    preset: PresetConfig
    job_type: JobType                      # "convert", "copy", "skip"
    is_lossy_source: Optional[bool] = None
    reason: Optional[str] = None
```

#### `JobResult`

Result of a ConversionJob.

```python
@dataclass
class JobResult:
    job: ConversionJob
    status: JobStatus                      # "SUCCESS", "FAILED", "SKIPPED"
    error_msg: Optional[str] = None
    stdout: Optional[str] = None
```

---

## `src/config/`

### `settings_loader.py`

Loads and validates `settings.yaml` into typed dataclasses.

#### Dataclasses

```python
@dataclass
class WineBackendConfig:
    wine_binary: str
    wine_prefix: Path
    coreconverter_path: str
    winepath_binary: str

@dataclass
class NativeBackendConfig:
    ffmpeg_binary: str
    flac_binary: str
    lame_binary: str
    opusenc_binary: str

@dataclass
class NativeDbpowerampConfig:
    coreconverter_path: str

@dataclass
class BackendConfig:
    default: str
    auto_detect: bool
    wine_dbpoweramp: WineBackendConfig
    native_dbpoweramp: NativeDbpowerampConfig
    native_ffmpeg: NativeBackendConfig

@dataclass
class ToolsConfig:
    pass  # empty for now

@dataclass
class HistoryConfig:
    db_path: str

@dataclass
class ExecutionConfig:
    default_workers: int
    probe_workers: int
    worker_model: str

@dataclass
class LoggingConfig:
    level: str

@dataclass
class Settings:
    backend: BackendConfig
    tools: ToolsConfig
    history: HistoryConfig
    execution: ExecutionConfig
    logging: LoggingConfig
```

#### Functions

```python
def load_settings(path: Path | str) -> Settings:
    """Parse and validate settings.yaml. Raises ConfigError on any malformed or invalid config."""
```

---

### `preset_loader.py`

Loads and validates `presets.yaml` into `PresetConfig` objects.

#### Functions

```python
def load_presets(path: Path | str) -> dict[str, PresetConfig]:
    """Parse and validate presets.yaml. Raises ConfigError on malformed or invalid config."""

def get_preset(presets: dict[str, PresetConfig], name: str) -> PresetConfig:
    """Look up a preset by name. Raises PresetNotFoundError with available names if not found."""
```

---

## `src/cli/args.py`

Command-line argument parsing and validation.

#### Functions

```python
def parse_args(argv: list[str] | None = None) -> "Namespace":
    """Parse command-line arguments."""

def validate_args(args: "Namespace") -> None:
    """Validate cross-flag rules. Raises SystemExit on validation failure."""
```

#### Argument Groups

| Group | Arguments |
|-------|-----------|
| Required | `-I`, `-O`, `-p` |
| Path options | `--source-path`, `--build-index`, `--index` |
| Backend options | `--backend`, `--auto-detect-backend`, `--no-auto-detect-backend` |
| Lossy handling | `--lossy-action`, `--no-lossy-check`, `--list-lossy` |
| Execution | `-w`, `--worker-model`, `--force` |
| Output | `-v`, `--dry-run` |
| History | `--db` |
| Excludes | `--exclude` |

---

## `src/audio/inspector.py`

Multi-tier lossy detection with cascade from fast to slow.

### Constants

#### Extension Sets

```python
UNAMBIGUOUS_LOSSLESS_EXT: frozenset[str] = {
    ".flac", ".fla", ".ape", ".wv", ".tta", ".tak",
    ".ofr", ".ofs", ".shn",
    ".wav", ".aiff", ".aif", ".caf", ".bwf", ".au", ".pcm", ".raw",
}

AMBIGUOUS_EXT: frozenset[str] = {
    ".m4a", ".mp4", ".caf",  # ALAC vs AAC
}

UNAMBIGUOUS_LOSSY_EXT: frozenset[str] = {
    ".mp3", ".mp2", ".mp1",
    ".ogg", ".opus", ".spx",
    ".wma", ".wmv", ".asf",
    ".ac3", ".eac3",
    ".dts", ".dtshd", ".dtsma",
    ".amr", ".amrnb", ".amrwb",
    ".ra", ".rm", ".rmvb",
    ".aac", ".adts", ".loas",
    ".3gp", ".3g2",
    ".webm",
}
```

#### Folder Tokens

```python
LOSSY_FOLDER_TOKENS: frozenset[str] = {
    "aac", "mp3", "v0", "v2",
    "128k", "192k", "256k", "320k",
    "128kbps", "192kbps", "256kbps", "320kbps",
    "lame", "l3tag",
    "ogg", "vorbis", "opus", "flac24",
    "webrip", "shoprip", "itunes", "amazon",
    "deezer", "spotify", "tidal", "qobuz",
    "mp3", "lossy",
}
```

#### Lossless Codecs

```python
LOSSLESS_CODECS: frozenset[str] = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "shorten", "als",
    "g711", "g711a", "g711u",
}
```

### Functions

```python
def is_lossy(file: Path) -> bool:
    """Three-tier lossy detection for a single file."""

def probe_many(files: list[Path], workers: int) -> dict[Path, bool]:
    """Three-tier lossy detection for a batch of files (blocking)."""

def probe_generator(files: list[Path], workers: int) -> tuple[Future, ...]:
    """Launch mutagen probes only for the Tier-3 ambiguous subset."""

def _is_lossy_by_ext(path: Path) -> Optional[bool]:
    """Tier 1: extension lookup."""

def _is_lossy_by_folder(path: Path) -> Optional[bool]:
    """Tier 2: folder-name heuristic."""

def _is_lossy_by_mutagen(file: Path) -> bool:
    """Tier 3: mutagen metadata probe."""

def _classify_by_ext_and_folder(files: list[Path]) -> dict[Path, Optional[bool]]:
    """Apply tiers 1 and 2 to every file in one synchronous pass."""
```

---

## `src/index/`

### `scanner.py`

File tree scanner with optional progress bar.

#### Classes

```python
@dataclass(frozen=False, slots=True)
class IndexRow:
    source_path: str
    dest_path: str
    job_type: str
    file_size: int
    sidecar_files: str
    mtime: float
    is_lossy: Optional[bool] = None
```

#### Functions

```python
def _discover_audio_files(input_path: Path, excludes: list[str]) -> list[Path]:
    """Return sorted list of audio files under input_path."""

def scan_with_progress(
    input_path: Path,
    excludes: list[str],
    preset,
    progress: ProgressSink,
) -> tuple[list[IndexRow], dict[Path, str]]:
    """Walk input_path once, collecting file stats and sidecar candidates."""

def _collect_sidecar_basenames(
    infile: Path,
    lyrics_policy,
    covers_policy,
) -> str:
    """Return newline-joined basenames of all existing sidecar files for infile."""
```

### `builder.py`

SQLite index database manager.

#### Classes

```python
class IndexBuilder:
    def __init__(self, db_path: Path) -> None:
        """Open SQLite connection and ensure table exists."""

    def add(self, row: IndexRow) -> None:
        """Insert a single row into the index."""

    def add_many(self, rows: list[IndexRow]) -> None:
        """Insert multiple rows using executemany."""

    def iter_rows(self) -> Iterator[IndexRow]:
        """Yield all rows in insertion order."""

    def commit(self) -> None:
        """Commit pending transaction."""

    def close(self) -> None:
        """Close the database connection."""

    @classmethod
    def from_existing(cls, db_path: Path) -> "IndexBuilder":
        """Open an existing index database."""

    def get_summary(self) -> dict[str, int | dict[str, int]]:
        """Get summary: total, lossy count, counts by job_type."""
```

### `cleanup.py`

#### Functions

```python
def cleanup_index(
    db_path: Path | None,
    failed_count: int,
    exception_info: str | None = None,
    interrupted: bool = False,
) -> None:
    """Delete tmp/index.db on success, preserve on failure/interrupt."""
```

---

## `src/jobs/builder.py`

Build ConversionJob lists from discovered audio files.

### Functions

```python
def enrich_index_rows_streaming(
    scan_rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
    progress: "ProgressSink",
    index_builder: IndexBuilder | None,
) -> list[Path]:
    """Stream-probe files, write rows to index DB incrementally."""

def enrich_index_rows(
    rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
) -> list[Path]:
    """Blocking convenience wrapper for enrich_index_rows_streaming."""

def build_jobs(
    files: list[Path],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
    index_rows_out: list[IndexRow] | None = None,
    sidecar_map: dict[Path, str] | None = None,
) -> tuple[list[ConversionJob], list[Path]]:
    """Build ConversionJob list from discovered audio files."""

def _classify(
    row: IndexRow,
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
) -> None:
    """Classify a single row and write it to the index DB."""
```

---

## `src/history/db.py`

SQLite history database wrapper.

### Classes

```python
class ConversionDB:
    def __init__(self, db_path: Path) -> None:
        """Open SQLite connection with WAL mode and busy timeout."""

    def get_record(self, source: str, dest: str) -> Optional[dict]:
        """Return history row matching (source_path, dest_path), or None."""

    def log_conversion(
        self,
        source: str,
        dest: str,
        job_type: str,
        command: Optional[str],
        status: str,
        error_msg: Optional[str] = None,
        stdout: Optional[str] = None,
    ) -> None:
        """Insert or update a history row."""

    def should_skip(
        self,
        source: str,
        dest: str,
        job_type: str,
        dest_file_exists: bool,
    ) -> bool:
        """Return True if job should be skipped based on history."""

    def close(self) -> None:
        """Close the SQLite connection."""
```

---

## `src/execution/`

### `runner.py`

Main entry point for job execution. Re-exports `run_all`, `run_job`, and `_drain_events_into_ui` from submodules.

### `run_all.py`

Top-level orchestrator — dispatch a list of jobs via a thread/process pool.

```python
def run_all(
    jobs: list[ConversionJob],
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    workers: int,
    worker_model: str,
    verbose: bool,
    progress: ProgressSink,
    print_to_terminal: bool = False,
) -> tuple[dict[str, int], list[Future], Queue, DBWriteQueue]:
    """Execute a list of ConversionJobs using a thread or process pool."""
```

Returns a tuple of (summary dict with success/skipped/failed counts, list of futures, events queue, write queue).

### `run_job.py`

Single-job execution — copy / convert / skip branches.

```python
def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """Execute a single ConversionJob."""
```

### `event_drain.py`

Drain worker events into the UI.

```python
def _drain_events_into_ui(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
) -> None:
    """Drain queued (JobEventKind, payload) tuples from workers and apply UI updates."""

def _run_event_drain_thread(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
    stop_event: Event,
) -> None:
    """Background thread that continuously drains the event queue and updates the UI."""
```

---

## `src/history/`

### `conversion_db.py`

Synchronous wrapper for conversion/copy history.

```python
class ConversionDB:
    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the history table exists."""

    def get_record(self, source: str, dest: str) -> Optional[dict]:
        """Return the row matching (source_path, dest_path), or None."""

    def log_conversion(
        self,
        source: str,
        dest: str,
        job_type: str,
        command: Optional[str],
        status: str,
        error_msg: Optional[str] = None,
        stdout: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> None:
        """Insert or update a history row with the current UTC timestamp."""

    def should_skip(
        self, source: str, dest: str, job_type: str, dest_file_exists: bool,
        dest_file_size: Optional[int] = None,
    ) -> bool:
        """Decide whether to skip a job based on history."""

    def close(self) -> None:
        """Close the SQLite connection."""
```

### `write_queue.py`

Async writer thread for conversion history.

```python
class DBWriteQueue:
    def __init__(self, db_path: Path, worker_model: str = "thread") -> None:
        """Initialize the writer thread."""

    def log_conversion(
        self,
        source: str,
        dest: str,
        job_type: str,
        command: Optional[str],
        status: str,
        error_msg: Optional[str] = None,
        stdout: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> None:
        """Queue a conversion log entry for async writing."""

    def flush(self) -> None:
        """Signal the writer to shut down and wait for it to finish."""
```

### `schema.py`

Shared history-table schema and pragmas.

```python
CREATE_HISTORY_TABLE_SQL: str
INSERT_OR_REPLACE_HISTORY_SQL: str
ADD_FILE_SIZE_COLUMN_SQL: str

def apply_history_pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL mode and busy-timeout on the given connection."""
```

---

## `src/jobs/`

### `builder.py`

Build ConversionJob lists from discovered audio files.

### `enrich.py`

Stream-probe and block-probe audio files for lossy classification.

```python
def enrich_index_rows_streaming(
    scan_rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
    progress: "ProgressSink",
    index_builder: IndexBuilder | None,
) -> list[Path]:
    """Stream-probe files, write rows to the index DB incrementally."""

def enrich_index_rows(
    rows: list[IndexRow],
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    probe_workers: int,
) -> list[Path]:
    """Blocking convenience wrapper for enrich_index_rows_streaming."""
```

### `classify.py`

Job type classification logic.

---

## `src/ui/progress/`

### `protocol.py`

ProgressSink protocol and SubtaskID.

```python
class SubtaskID:
    """Opaque wrapper around per-job bar identifier."""

class ProgressSink(Protocol):
    def start_phase(self, name: str, total: int) -> None: ...
    def advance(self, amount: int = 1) -> None: ...
    def start_subtask(self, name: str) -> SubtaskID: ...
    def finish_subtask(self, subtask_id: SubtaskID) -> None: ...
    def log(self, message: str) -> None: ...
    def stop(self) -> None: ...
    def stop_phase(self) -> None: ...
    def set_activity(self, activity: str) -> None: ...
    def log_file(self, message: str) -> None: ...
    def log_phase(self, name: str) -> None: ...
    def set_phase_label(self, label: str) -> None: ...
```

### `renderer.py`

Self-contained progress-bar renderer for RichProgressSink.

```python
class _BarState:
    """Lightweight mutable state for one progress bar."""

class _ProgressRenderer:
    """Self-contained progress-bar renderer."""

    BAR_WIDTH: int = 18
    MAX_VISIBLE_BARS: int  # Computed based on terminal width

    def set_phase_name(self, name: str) -> None: ...
    def set_activity(self, activity: str) -> None: ...
    def add_bar(self, description: str, total: int | None = None) -> int: ...
    def finish_bar(self, bar_id: int) -> None: ...
    def render(self) -> Table: ...
```

### `rich_sink.py`

RichProgressSink backed by rich.live.Live.

```python
class RichProgressSink:
    """Concrete ProgressSink backed by rich.live.Live."""

    def __init__(
        self,
        total_files: int | None = None,
        total_bytes: int | None = None,
    ) -> None: ...

    def start_phase(self, name: str, total: int) -> None: ...
    def advance(self, amount: int = 1) -> None: ...
    def start_subtask(self, name: str) -> SubtaskID: ...
    def finish_subtask(self, subtask_id: SubtaskID) -> None: ...
    def log(self, message: str) -> None: ...
    def stop(self) -> None: ...
    def stop_phase(self) -> None: ...
    def set_activity(self, activity: str) -> None: ...
    def log_file(self, message: str) -> None: ...
    def log_phase(self, name: str) -> None: ...
    def set_phase_label(self, label: str) -> None: ...
```

### `NullProgressSink` and `VerboseProgressSink`

Additional sink implementations:
- `NullProgressSink` — No-op sink for verbose mode (disables progress bar)
- `VerboseProgressSink` — Logs to stdout for --verbose mode

### Enums

```python
class JobEventKind(str, Enum):
    STARTED = "started"
    FINISHED = "finished"
    LOG = "log"
    ACTIVITY = "activity"
```

### Functions

```python
def run_all(
    jobs: list[ConversionJob],
    backend: ConversionBackend,
    db: ConversionDB,
    force: bool,
    workers: int,
    worker_model: str,
    verbose: bool,
    progress: ProgressSink,
) -> tuple[dict[str, int], list[Future], Queue]:
    """Execute jobs using thread or process pool."""

def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """Execute a single ConversionJob."""

def _drain_events_into_ui(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
) -> None:
    """Drain queued events and apply UI updates."""

def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    """Verify output file exists and has non-zero size."""
```

---

## `src/pathing/resolver.py`

Path resolution and transformation.

### Functions

```python
def compute_output_path(
    infile: Path,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    target_ext: str,
) -> Path:
    """Compute the output path for a given input file."""

def validate_source_path(input_path: Path, source_path: Path) -> None:
    """Validate that input_path is source_path or inside it."""

def hide_filename(name: str) -> str:
    """Hide a filename by prefixing it with a dot."""

def to_wine_path(
    linux_path: Path,
    wine_binary: str,
    wine_prefix: str,
    winepath_binary: str,
) -> str:
    """Translate a Linux path to Windows path using winepath."""
```

---

## `src/sidecars/manager.py`

Sidecar file copying.

### Functions

```python
def copy_lyrics(
    infile: Path,
    outfile: Path,
    policy: SidecarPolicy | None,
) -> list[Path]:
    """Copy lyric/text files next to output."""

def copy_covers(
    infile: Path,
    outfile: Path,
    policy: CoverPolicy | None,
) -> list[Path]:
    """Copy cover art files to output directory."""
```

---

## `src/ui/progress_view.py`

Rich-based progress display.

### Protocols

```python
class ProgressSink(Protocol):
    def start_phase(self, name: str, total: int) -> None: ...
    def advance(self, amount: int = 1) -> None: ...
    def start_subtask(self, name: str) -> SubtaskID: ...
    def finish_subtask(self, subtask_id: SubtaskID) -> None: ...
    def log(self, message: str) -> None: ...
    def stop(self) -> None: ...
    def stop_phase(self) -> None: ...
    def set_activity(self, activity: str) -> None: ...
```

### Classes

```python
class SubtaskID:
    """Opaque wrapper around per-job bar identifier."""

class RichProgressSink:
    """Concrete ProgressSink backed by rich.live.Live."""

    def __init__(
        self,
        total_files: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        ...

class _ProgressRenderer:
    """Self-contained progress-bar renderer."""

class _BarState:
    """Lightweight mutable state for one progress bar."""
```

---

## `src/backends/base.py`

Abstract base class for conversion backends.

### Classes

```python
class ConversionBackend(ABC):
    @abstractmethod
    def name(self) -> Backend:
        """Return the backend identifier."""

    @abstractmethod
    def validate_environment(self) -> None:
        """Check that required binaries/paths/prefix exist."""

    @abstractmethod
    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains this backend's key."""

    @abstractmethod
    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion and return a JobResult."""
```

---

## `src/backends/registry.py`

Backend factory with fail-fast validation.

### Functions

```python
def resolve_backend_for_run(
    cli_backend: Backend | None,
    settings: Settings,
) -> Backend:
    """Return the Backend to use for this run."""

def detect_backend_for_run(
    cli_backend: Backend | None,
    settings: Settings,
    preset: PresetConfig,
    platform: str,
    auto_detect_override: bool | None = None,
) -> Backend:
    """Resolve the effective Backend using priority rules."""

def get_backend(name: Backend, settings: Settings) -> ConversionBackend:
    """Instantiate and return the requested ConversionBackend."""
```

### Exceptions

```python
class UnknownBackendError(ConfigError):
    """Raised when a backend name is not recognised."""
```
