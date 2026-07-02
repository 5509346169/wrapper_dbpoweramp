---
title: Module Reference
summary: Every src/ module with classes, dataclasses, and key functions.
audience: [engineer]
type: reference
weight: 20
---

This document provides detailed reference for each module in the `src/` package. For the architectural role of each module and how they interact at runtime, see [Architecture]({{< relref "architecture" >}}).

## Package structure

```text
src/
├── __init__.py
├── exceptions.py              # Custom exception classes
├── app/                       # Post-refactor application structure
│   ├── context.py             # AppContext + build_context(args)
│   ├── backend.py             # Backend resolution
│   ├── commands/              # CLI command implementations
│   ├── lifecycle/             # tmp/, scan-cache, signals
│   └── pipeline/              # scan/enrich/execute orchestrators
├── audio/
│   ├── inspector.py           # Multi-tier lossy detection
│   ├── integrity.py           # VerifyStatus, verify_file()
│   └── verify_backends.py     # soundfile/miniaudio/mutagen verifiers
├── backends/
│   ├── base.py                # ConversionBackend ABC
│   ├── registry.py            # Backend factory + selection
│   ├── native_ffmpeg.py
│   ├── native_dbpoweramp.py
│   └── wine_dbpoweramp.py
├── cli/
│   ├── args.py                # argparse + validation
│   └── db_cmd.py              # db {check,migrate,doctor} subcommands
├── config/
│   ├── settings_loader.py
│   └── preset_loader.py
├── execution/
│   ├── events.py
│   ├── event_drain.py
│   ├── run_job.py
│   └── run_all.py
├── history/
│   ├── conversion_db.py
│   ├── write_queue.py
│   ├── migrations.py
│   └── schema.py
├── index/
│   ├── scanner.py
│   ├── builder.py
│   ├── cleanup.py
│   └── scan_cache.py
├── jobs/
│   ├── builder.py
│   ├── enrich.py
│   └── classify.py
├── models/
│   └── types.py
├── pathing/
│   └── resolver.py
├── sidecars/
│   └── manager.py
└── ui/
    ├── progress_view.py
    └── progress/
        ├── protocol.py
        ├── renderer.py
        ├── rich_sink.py
        ├── verbose_sink.py
        └── null_sink.py
```

## `src/app/`

Post-refactor application structure. All modules are internal.

### `context.py`

`AppContext` frozen dataclass bundles `args`, `settings`, `preset`, `backend`, `backend_name`, `db_path`, `workers`, `worker_model`, `execution_mode`, `verbose`. `build_context(args) -> AppContext` factory resolves all fields from the parsed CLI namespace.

### `backend.py`

`_resolve_backend_name()` + `supports()` compatibility gate.

### `lifecycle/signals.py`

`SignalGuard` context manager — installs SIGINT/SIGTERM handlers, yields a guard whose `.interrupted` flag is set by the handlers, restores originals on exit.

### `lifecycle/tempdir.py`

`tmp/` directory lifecycle (create on entry, delete on clean exit, preserve on failure/interrupt).

### `lifecycle/scan_cache.py`

Scan cache open/close wrapper.

### `pipeline/scan.py`

`scan_with_progress` / `load_rows_from_cache` orchestration.

### `pipeline/enrich.py`

Calls `src/jobs/enrich.py` for lossy probe.

### `pipeline/jobs.py`

`_row_to_job` + lossy-gate check.

### `pipeline/prefilter.py`

`should_skip` loop + pre-verify gate (`--verify-skip`).

### `pipeline/phases.py`

`_run_jobs_by_phase` (phased execution mode).

### `pipeline/execute.py`

Verbose/Rich sink + `run_all` loop + futures draining.

### `pipeline/reporting.py`

Final "Done. Success: ..." summary + `_format_bytes`.

### `commands/`

| Module | Entry point |
|--------|-------------|
| `commands/build_index.py` | `cmd_build_index(ctx)` |
| `commands/run_from_index.py` | `cmd_run_from_index(ctx)` |
| `commands/run_pipeline.py` | Main scan + enrich + execute flow |
| `commands/dry_run.py` | `cmd_dry_run(ctx)` |
| `commands/list_lossy.py` | `cmd_list_lossy(ctx)` |
| `commands/db_check.py` | `db check` / `--db-version` entry point |
| `commands/db_migrate.py` | `db migrate` entry point |

## `src/exceptions.py`

Custom exception classes for the application.

### Classes

#### `ConfigError`

```python
class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or fails validation."""
```

#### `PresetNotFoundError`

```python
class PresetNotFoundError(Exception):
    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
```

#### `ProbeError`

```python
class ProbeError(Exception):
    def __init__(self, file: str, stderr: str) -> None:
        self.file = file
        self.stderr = stderr
```

#### `PathConfigError`

```python
class PathConfigError(Exception):
    """Raised when a path configuration is invalid."""
```

#### `BackendError`

```python
class BackendError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
```

#### `IndexError`

```python
class IndexError(Exception):
    """Raised when the temporary index database cannot be created, opened, or written."""
```

## `src/models/types.py`

Pure dataclass and enum types — no I/O operations.

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

### Type aliases

```python
JobType   = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
```

### Constants

```python
AUDIO_EXTENSIONS: set[str] = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".ape", ".wv", ".tta"}
```

### Dataclasses

#### `SidecarPolicy`

```python
@dataclass
class SidecarPolicy:
    copy: bool = False
    extensions: list[str] = field(default_factory=list)
    hide: bool = False
```

#### `CoverPolicy`

```python
@dataclass
class CoverPolicy:
    copy: bool = False
    patterns: list[str] = field(default_factory=list)
    hide: bool = False
```

#### `BackendPresetArgs`

```python
@dataclass
class BackendPresetArgs:
    encoder: Optional[str] = None
    tool: Optional[str] = None
    args: list[str] = field(default_factory=list)
    requires_encoder: Optional[str] = None
```

#### `PresetConfig`

```python
@dataclass
class PresetConfig:
    name: str
    ext: str
    backends: dict[Backend, BackendPresetArgs]
    lyrics: Optional[SidecarPolicy] = None
    covers: Optional[CoverPolicy] = None
```

#### `ConversionJob`

```python
@dataclass
class ConversionJob:
    infile: Path
    outfile: Path
    preset: PresetConfig
    job_type: JobType
    is_lossy_source: Optional[bool] = None
    reason: Optional[str] = None
```

#### `JobResult`

```python
@dataclass
class JobResult:
    job: ConversionJob
    status: JobStatus
    error_msg: Optional[str] = None
    stdout: Optional[str] = None
```

## `src/config/`

### `settings_loader.py`

Loads and validates `settings.yaml` into typed dataclasses.

```python
def load_settings(path: Path | str) -> Settings:
    """Parse and validate settings.yaml. Raises ConfigError on any malformed or invalid config."""
```

### `preset_loader.py`

```python
def load_presets(path: Path | str) -> dict[str, PresetConfig]:
    """Parse and validate presets.yaml. Raises ConfigError on malformed or invalid config."""

def get_preset(presets: dict[str, PresetConfig], name: str) -> PresetConfig:
    """Look up a preset by name. Raises PresetNotFoundError with available names if not found."""
```

## `src/cli/args.py`

Command-line argument parsing and validation.

```python
def parse_args(argv: list[str] | None = None) -> "Namespace":
    """Parse command-line arguments."""

def validate_args(args: "Namespace") -> None:
    """Validate cross-flag rules. Raises SystemExit on validation failure."""
```

## `src/audio/inspector.py`

Multi-tier lossy detection with cascade from fast to slow.

```python
def is_lossy(file: Path) -> bool:
    """Three-tier lossy detection for a single file."""

def probe_many(files: list[Path], workers: int) -> dict[Path, bool]:
    """Three-tier lossy detection for a batch of files (blocking)."""
```

## `src/audio/integrity.py`

Post-conversion integrity verification. `VerifyStatus` enum: `OK`, `NOT_OK`, `UNSUPPORTED`. `VerifyResult` dataclass: `status`, `reason`, `fmt`, `duration_s`, plus `result.short` property returning `Okay` / `Not - ...` / `Skipped - ...`. `verify_file(path) -> VerifyResult` dispatches to the best backend (soundfile → miniaudio → mutagen) at call time.

## `src/index/scanner.py`

File tree scanner with optional progress bar.

```python
def scan_with_progress(
    input_path: Path,
    excludes: list[str],
    preset,
    progress: ProgressSink,
) -> tuple[list[IndexRow], dict[Path, str]]:
    """Walk input_path once, collecting file stats and sidecar candidates."""
```

## `src/index/builder.py`

SQLite index database manager.

```python
class IndexBuilder:
    def __init__(self, db_path: Path) -> None:
        """Open SQLite connection and ensure table exists."""

    def add(self, row: IndexRow) -> None:
        """Insert a single row into the index."""

    def iter_rows(self) -> Iterator[IndexRow]:
        """Yield all rows in insertion order."""

    def commit(self) -> None:
        """Commit pending transaction."""

    def get_summary(self) -> dict[str, int | dict[str, int]]:
        """Get summary: total, lossy count, counts by job_type."""
```

## `src/jobs/enrich.py`

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
```

## `src/history/conversion_db.py`

Synchronous wrapper for conversion/copy history.

```python
class ConversionDB:
    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the history table exists. Auto-runs migrate_to_current() on first open."""

    def log_conversion(
        self,
        source: str,
        dest: str,
        job_type: str,
        command: Optional[str],
        status: str,
        error_msg: Optional[str] = None,
        stdout: Optional[str] = None,
        verify_status: Optional[str] = None,
        verify_reason: Optional[str] = None,
        verify_format: Optional[str] = None,
        verify_duration_s: Optional[float] = None,
    ) -> None:
        """Insert or update a history row with the current UTC timestamp."""

    def should_skip(
        self, source: str, dest: str, job_type: str, dest_file_exists: bool,
        dest_file_size: Optional[int] = None,
    ) -> bool:
        """Decide whether to skip a job based on history."""
```

## `src/history/write_queue.py`

Async writer thread for conversion history.

```python
class DBWriteQueue:
    def __init__(self, db_path: Path, worker_model: str = "thread") -> None:
        """Initialize the writer thread."""

    def log_conversion(self, ...) -> None:
        """Queue a conversion log entry for async writing."""

    def flush(self) -> None:
        """Signal the writer to shut down and wait for it to finish."""
```

## `src/history/migrations.py`

Schema versioning and migration orchestrator. `SCHEMA_VERSION = 2` (current). `MIGRATIONS` list maps `(from_ver, to_ver, run_once_sql, row_backfill_sql)`. `migrate_to_current(db_path)` runs pending migrations in a single transaction. `get_db_version(db_path) -> DbVersionInfo` is read-only.

## `src/ui/progress/protocol.py`

```python
class ProgressSink(Protocol):
    def start_phase(self, name: str, total: int) -> None: ...
    def advance(self, amount: int = 1) -> None: ...
    def start_subtask(self, name: str) -> SubtaskID: ...
    def finish_subtask(self, subtask_id: SubtaskID) -> None: ...
    def log(self, message: str) -> None: ...
    def stop(self) -> None: ...
```

## `src/ui/progress/rich_sink.py`

```python
class RichProgressSink:
    """Concrete ProgressSink backed by rich.live.Live."""
```

## `src/pathing/resolver.py`

Path resolution and transformation.

```python
def compute_output_path(
    infile: Path,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    target_ext: str,
) -> Path:
    """Compute the output path for a given input file."""

def to_wine_path(
    linux_path: Path,
    wine_binary: str,
    wine_prefix: str,
    winepath_binary: str,
) -> str:
    """Translate a Linux path to Windows path using winepath."""
```

## `src/sidecars/manager.py`

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

## `src/backends/base.py`

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

## `src/backends/registry.py`

Backend factory with fail-fast validation.

```python
def get_backend(name: Backend, settings: Settings) -> ConversionBackend:
    """Instantiate and return the requested ConversionBackend."""
```
