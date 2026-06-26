# Module Reference

This document provides detailed reference for each module in the `src/` package.

---

## Package Structure

```
src/
├── __init__.py
├── exceptions.py                # Custom exception classes
├── audio/
│   ├── __init__.py
│   ├── inspector.py            # Backward-compat shim (re-exports)
│   ├── extensions.py           # Tier 1: file-extension lookup
│   ├── folder_heuristic.py     # Tier 2: folder-name heuristic
│   ├── mutagen_probe.py        # Tier 3: mutagen metadata probe
│   ├── cascade.py              # Three-tier single-file cascade
│   └── batch.py                # Batch / parallel-future utilities
├── backends/
│   ├── __init__.py
│   ├── base.py                 # ConversionBackend ABC
│   ├── registry.py             # Backend factory
│   ├── native_ffmpeg.py        # FFmpeg backend
│   ├── native_dbpoweramp.py    # Native dBpoweramp backend
│   └── wine_dbpoweramp.py      # Wine dBpoweramp backend
├── cli/
│   ├── __init__.py
│   └── args.py                 # Argument parsing
├── config/
│   ├── __init__.py
│   ├── models.py               # settings.yaml dataclasses
│   ├── settings_loader.py      # settings.yaml loader
│   └── preset_loader.py        # presets.yaml loader
├── execution/
│   ├── __init__.py
│   ├── runner.py               # Backward-compat shim (re-exports)
│   ├── events.py               # JobEventKind + queue helpers
│   ├── event_drain.py          # UI drain (single + thread)
│   ├── run_job.py              # Single-job execution
│   └── run_all.py              # Thread/process pool orchestrator
├── history/
│   ├── __init__.py
│   ├── db.py                   # Backward-compat shim (re-exports)
│   ├── schema.py               # CREATE TABLE / INSERT / pragmas
│   ├── conversion_db.py        # Synchronous read/write wrapper
│   └── write_queue.py          # Async writer thread
├── index/
│   ├── __init__.py
│   ├── scanner.py              # File scanning
│   ├── schema.py               # CREATE TABLE / INSERT / pragmas / migration
│   ├── builder.py              # SQLite index (batched writes)
│   └── cleanup.py              # Index cleanup
├── jobs/
│   ├── __init__.py
│   ├── builder.py              # Backward-compat shim (re-exports)
│   ├── classify.py             # job_type decision + IndexRow mutation
│   ├── enrich.py               # Streaming + blocking probe pipelines
│   └── build_jobs.py           # ConversionJob list construction
├── models/
│   ├── __init__.py
│   └── types.py                # Dataclass types
├── pathing/
│   ├── __init__.py
│   └── resolver.py             # Path resolution
├── sidecars/
│   ├── __init__.py
│   └── manager.py              # Sidecar file copying
└── ui/
    ├── __init__.py
    ├── progress_view.py        # Backward-compat shim (re-exports)
    └── progress/
        ├── protocol.py         # ProgressSink protocol, SubtaskID
        ├── renderer.py         # Self-contained progress-bar renderer
        ├── rich_sink.py        # RichProgressSink (rich.live.Live)
        ├── verbose_sink.py     # VerboseProgressSink
        └── null_sink.py        # NullProgressSink
```

The shim modules (`audio/inspector.py`, `history/db.py`, `execution/runner.py`,
`jobs/builder.py`, `ui/progress_view.py`) re-export the names that used to live
in their single-file implementations, so `from src.audio.inspector import
is_lossy` and similar imports keep working unchanged.

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

### `models.py`

Dataclasses describing the structure of `settings.yaml`. These are imported by
`settings_loader.py` and re-exported from there for backwards compatibility.

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

### `settings_loader.py`

Loads and validates `settings.yaml` into typed dataclasses. The dataclasses
themselves live in :mod:`src.config.models`; this module re-exports them so
existing imports (`from src.config.settings_loader import Settings`) keep
working.

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

## `src/audio/`

Audio inspection and lossy detection. The original single-file
`inspector.py` was split into a small set of single-responsibility modules.
`inspector.py` remains as a backward-compat shim that re-exports the same
public/private names — including `MutagenFile`, which tests
monkey-patch — so existing imports keep working.

### Extension sets (`src/audio/extensions.py`)

```python
UNAMBIGUOUS_LOSSLESS_EXT: frozenset[str] = {
    ".flac", ".fla", ".ape", ".wv", ".tta", ".tak",
    ".ofr", ".ofs", ".shn",
    ".wav", ".aiff", ".aif", ".caf", ".bwf", ".au", ".pcm", ".raw",
}

AMBIGUOUS_EXT: frozenset[str] = {
    ".m4a", ".caf",           # ALAC vs AAC
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

ALL_LOSSY_EXT: frozenset[str] = UNAMBIGUOUS_LOSSY_EXT | AMBIGUOUS_EXT
```

### Folder tokens (`src/audio/folder_heuristic.py`)

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

The folder heuristic stops at fully-numeric directory names (e.g. album IDs in
sequential scans) and at the filesystem root, to avoid false positives.

### Lossless codecs (`src/audio/mutagen_probe.py`)

```python
LOSSLESS_CODECS: frozenset[str] = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "shorten", "als",
    "g711", "g711a", "g711u",
}
```

Tier 3 falls back to `info.codec_description` when `info.codec` is empty or
`"unknown"`, and raises `ProbeError` if neither field resolves to a known
codec.

### Public functions

```python
def is_lossy(file: Path) -> bool:
    """Three-tier lossy detection for a single file (in src/audio/cascade.py)."""

def probe_many(files: list[Path], workers: int) -> dict[Path, bool]:
    """Three-tier lossy detection for a batch of files (blocking).

    Extension and folder-name checks are applied synchronously first;
    mutagen runs only on the ambiguous subset in a thread pool.
    """

def probe_generator(files: list[Path], workers: int) -> tuple[Future, ...]:
    """Launch mutagen probes only for the Tier-3 ambiguous subset."""

def _classify_by_ext_and_folder(files: list[Path]) -> dict[Path, Optional[bool]]:
    """Apply tiers 1 and 2 to every file in one synchronous pass."""

def _is_lossy_by_ext(path: Path) -> Optional[bool]:
    """Tier 1: extension lookup (in src/audio/extensions.py)."""

def _is_lossy_by_folder(path: Path) -> Optional[bool]:
    """Tier 2: folder-name heuristic (in src/audio/folder_heuristic.py)."""

def _is_lossy_by_mutagen(file: Path) -> bool:
    """Tier 3: mutagen metadata probe (in src/audio/mutagen_probe.py)."""
```

`MutagenFile` is also re-exported from the `inspector.py` shim so existing
`patch('src.audio.inspector.MutagenFile')` test stubs continue to work.

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

### `schema.py`

Shared index_entries table schema, INSERT template, pragmas, and the
`is_lossy` column migration. Lives next to `builder.py` so the schema can be
referenced from migrations or tests without importing the class.

```python
CREATE_INDEX_ENTRIES_TABLE_SQL: str
INSERT_INDEX_ENTRY_SQL: str
IS_LOSSY_COLUMN_MIGRATION: str

def apply_index_pragmas(conn: sqlite3.Connection) -> None:
    """Set WAL mode and synchronous=NORMAL for fast bulk inserts."""

def ensure_is_lossy_column(conn: sqlite3.Connection) -> None:
    """Add ``is_lossy`` to tables created by older versions."""
```

### `builder.py`

SQLite index database manager with batched inserts.

```python
class IndexBuilder:
    _BATCH_SIZE: int = 1000     # auto-flush threshold

    def __init__(self, db_path: Path) -> None:
        """Open SQLite connection and ensure table exists; migrates older tables."""

    def add(self, row: IndexRow) -> None:
        """Buffer a single row; auto-flushes every _BATCH_SIZE rows."""

    def add_many(self, rows: list[IndexRow]) -> None:
        """Insert multiple rows using executemany."""

    def iter_rows(self) -> Iterator[IndexRow]:
        """Yield all rows in insertion order."""

    def commit(self) -> None:
        """Flush any buffered rows and commit the transaction."""

    def close(self) -> None:
        """Close the database connection."""

    def __enter__(self) -> "IndexBuilder": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """commit() + close()."""

    @classmethod
    def from_existing(cls, db_path: Path) -> "IndexBuilder":
        """Open an existing index database. Raises FileNotFoundError if missing."""

    def get_summary(self) -> dict[str, int | dict[str, int]]:
        """Get summary: total, lossy count, counts by job_type, total_bytes."""
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

## `src/jobs/`

Build `ConversionJob` lists from discovered audio files. The original
single-file `builder.py` was split into `classify.py`, `enrich.py`, and
`build_jobs.py`. `builder.py` remains as a backward-compat shim that
re-exports the same public/private names (including `compute_output_path`,
which tests monkey-patch here).

### `src/jobs/classify.py`

```python
def decide_job_type(
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
) -> str:
    """Pure helper: pick job_type based on lossy status and configured action."""

def classify(
    row: IndexRow,
    is_lossy_val: bool | None,
    lossy_action: LossyAction | None,
    no_lossy_check: bool,
    input_root: Path,
    source_root: Path | None,
    output_root: Path,
    preset: PresetConfig,
) -> None:
    """Classify a single row and write it to the index DB immediately.

    Mutates ``row`` in-place via ``object.__setattr__`` (IndexRow is frozen).
    """
```

### `src/jobs/enrich.py`

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
    """Stream-probe files, write rows to the index DB incrementally.

    Uses a single "Probing" progress bar whose phase label flips
    (Extension -> Folder -> Mutagen) to reflect which tier resolved
    the most recent file. Each file walks the cascade independently
    inside its worker thread — there are no per-tier serial barriers,
    so every worker is always busy on the deepest tier its current
    file requires.
    """

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

### `src/jobs/build_jobs.py`

```python
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
```

The names below remain importable from `src.jobs.builder` (the backward-compat
shim):

```python
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
    """Classify a single row and write it to the index DB (alias of jobs.classify.classify)."""
```

---

## `src/history/`

SQLite history database. The original single-file `db.py` was split into a
`schema.py` shared module, a synchronous `ConversionDB`, and an async
`DBWriteQueue`. `db.py` remains as a backward-compat shim that re-exports
both classes.

### `src/history/schema.py`

```python
CREATE_HISTORY_TABLE_SQL: str
INSERT_OR_REPLACE_HISTORY_SQL: str

def apply_history_pragmas(conn: sqlite3.Connection) -> None:
    """Enable WAL mode and busy-timeout on the given connection."""
```

### `src/history/conversion_db.py`

```python
class ConversionDB:
    def __init__(self, db_path: Path) -> None:
        """Open the SQLite connection and ensure the history table exists."""

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

### `src/history/write_queue.py`

```python
class DBWriteQueue:
    """Async writer for conversion history.

    Workers push log entries onto a queue; a single background thread
    drains the queue and writes to SQLite sequentially, eliminating all
    concurrent write contention.
    """

    def __init__(self, db_path: Path) -> None:
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
    ) -> None:
        """Queue a conversion log entry for async writing."""

    def flush(self) -> None:
        """Signal the writer to shut down and wait for it to finish (up to 5s)."""
```

---

## `src/execution/`

Job execution with thread/process pools. The package is split into
`events.py`, `event_drain.py`, `run_job.py`, and `run_all.py`, with
`runner.py` re-exporting the same public/private names for backwards
compatibility.

### Enums (`src/execution/events.py`)

```python
class JobEventKind(str, Enum):
    STARTED = "started"
    FINISHED = "finished"
    LOG = "log"
    ACTIVITY = "activity"
```

### Queue helpers (`src/execution/events.py`)

```python
def _make_event_queue(worker_model: str) -> Queue:
    """Build a thread/process-safe queue for cross-worker UI events.

    For process workers a ``multiprocessing.Manager().Queue()`` is used
    because raw ``multiprocessing.Queue`` cannot be pickled into a spawn-based
    worker (Windows default).
    """

def _push_log_event(events: Queue, line: str) -> None:
    """Module-level picklable sink used by workers to enqueue verbose lines."""

def _build_stream_callback(events: Queue) -> Optional[Callable[[str], None]]:
    """Build a stream_callback that forwards verbose lines to the main thread."""
```

### `src/execution/run_job.py`

```python
def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    """Verify the output file exists and has non-zero size."""

def run_job(
    job: ConversionJob,
    backend: ConversionBackend,
    db_path: str,
    write_queue: DBWriteQueue,
    force: bool,
    stream_callback: Optional[Callable[[str], None]],
    events: Optional[Queue] = None,
) -> tuple[JobStatus, str, str | None]:
    """Execute a single ConversionJob (copy / convert / skip branches).

    Each branch is responsible for calling ``write_queue.log_conversion(...)``
    after a successful convert/copy so the writer thread picks it up.
    """
```

### `src/execution/event_drain.py`

```python
def _drain_events_into_ui(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
) -> None:
    """Drain queued events and apply UI updates on the calling thread.

    STARTED adds an indeterminate per-job bar; FINISHED removes it and
    advances the master bar; ACTIVITY updates the activity indicator;
    LOG appends a message to the log area.
    """

def _run_event_drain_thread(
    events: Queue,
    progress: ProgressSink,
    job_tasks: dict[str, SubtaskID],
    stop_event: Event,
) -> None:
    """Long-lived background drain thread used while run_all is active."""
```

### `src/execution/run_all.py`

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
    """Execute jobs using thread or process pool.

    Returns ``(summary, futures, events_queue, write_queue)``. The caller
    MUST call ``write_queue.flush()`` after all futures complete so the
    background writer thread exits cleanly.
    """
```

The signature has changed from earlier versions: ``db`` is no longer a
``ConversionDB`` instance — the orchestrator now constructs an async
``DBWriteQueue`` itself and passes it to each worker, with ``db_path`` as a
plain string.

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
