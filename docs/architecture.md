# Architecture

This document provides an overview of the system architecture for wrapper-dbpoweramp, explaining how the components fit together.

---

## High-Level Architecture

The wrapper is organized into a pipeline of independent, composable stages:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   CLI       │────▶│   Index     │────▶│   Jobs      │────▶│  Execution  │
│   Args      │     │   Scanner   │     │   Builder   │     │   Runner    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │                   │
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Settings   │     │  Audio      │     │  Conversion │     │  Backends   │
│  Loader     │     │  Inspector  │     │  Job Model  │     │  (FFmpeg,   │
│             │     │             │     │             │     │   dBpoweramp)│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Component Overview

### Entry Point (`main.py`)

The `main.py` module is the orchestrator that:

1. Parses command-line arguments
2. Loads configuration files (`settings.yaml`, `presets.yaml`)
3. Resolves the appropriate backend based on CLI flags and auto-detection
4. Manages the conversion pipeline: scan → probe → build jobs → execute
5. Handles signal handlers for graceful interruption
6. Manages the temporary index database lifecycle

### Core Packages

#### `src/cli/`

Handles command-line argument parsing and validation.

**Key modules:**
- `args.py` - Argument parser using `argparse`

**Key functions:**
- `parse_args()` - Parse command-line arguments
- `validate_args()` - Validate cross-flag rules

**CLI Flags:**
| Flag | Description |
|------|-------------|
| `-I, --input` | Input file or directory |
| `-O, --output` | Output root directory |
| `-p, --preset` | Preset name |
| `--backend` | Backend override |
| `--lossy-action` | What to do with lossy sources |
| `--force` | Ignore resume history |
| `--dry-run` | List jobs without converting |

---

#### `src/config/`

Loads and validates configuration files.

**Key modules:**
- `settings_loader.py` - Loads `settings.yaml` into typed dataclasses
- `preset_loader.py` - Loads `presets.yaml` into `PresetConfig` objects

**Key functions:**
- `load_settings()` - Parse and validate `settings.yaml`
- `load_presets()` - Parse and validate `presets.yaml`
- `get_preset()` - Look up a preset by name

**Configuration schema:**

```yaml
backend:
  default: "native_ffmpeg"
  auto_detect: true
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
  wine_dbpoweramp:
    wine_binary: "wine"
    wine_prefix: "~/.wine-dbpoweramp"
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
    winepath_binary: "winepath"
  native_ffmpeg:
    ffmpeg_binary: "ffmpeg"
    flac_binary: "flac"
    lame_binary: "lame"
    opusenc_binary: "opusenc"

tools: {}

history:
  db_path: "conversion_history.db"

execution:
  default_workers: 4
  probe_workers: 16
  worker_model: "thread"

logging:
  level: "INFO"
```

---

#### `src/models/`

Pure dataclass types - no I/O operations.

**Key types:**
- `Backend` (enum) - Backend identifiers
- `LossyAction` (enum) - Lossy source handling actions
- `PresetConfig` - Full encoding preset definition
- `ConversionJob` - A single file to be processed
- `JobResult` - Result of a ConversionJob
- `SidecarPolicy` - Sidecar file copy policy
- `CoverPolicy` - Cover image copy policy

---

#### `src/backends/`

Conversion backend implementations.

**Key modules:**
- `base.py` - Abstract `ConversionBackend` base class
- `registry.py` - Factory for backend instances with fail-fast validation
- `native_ffmpeg.py` - FFmpeg-based conversion
- `wine_dbpoweramp.py` - dBpoweramp via Wine
- `native_dbpoweramp.py` - Native dBpoweramp on Windows

**Backend interface:**

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
    def run(self, job: ConversionJob, stream_callback) -> JobResult:
        """Execute the conversion and return a JobResult."""
```

**Backend resolution order:**

1. If `--backend NAME` is given on the command line, that wins outright.
2. Otherwise, if `auto_detect` is enabled and the platform is Windows, and the selected preset has a `native_dbpoweramp` block, use `native_dbpoweramp`.
3. Otherwise, fall back to `backend.default` from `settings.yaml`.

---

#### `src/index/`

File indexing and scanning.

**Key modules:**
- `scanner.py` - File tree scanner with optional progress bar. When
  given a `ScanCache`, writes each scanned row into it during the walk
  so the probe phase can skip the directory traversal on subsequent runs.
- `builder.py` - SQLite index database manager
- `cleanup.py` - Index cleanup utilities
- `scan_cache.py` - Per-run scan-cache (`ScanCache`). Writes a small
  path-only SQLite snapshot to `./tmp/scan_cache_<hash>.db` and reads
  it back on subsequent runs to skip the directory walk.

**Key classes:**
- `IndexRow` - A row in the temp index snapshot
- `IndexBuilder` - Manages the index_entries SQLite table
- `ScanCache` - Manages the scan_cache_* SQLite table (path+size+mtime
  +sidecar_files, no probe-derived fields)

**Index schema:**

```sql
CREATE TABLE index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path  TEXT NOT NULL,
    dest_path    TEXT NOT NULL,
    job_type     TEXT NOT NULL,
    file_size    INTEGER NOT NULL,
    sidecar_files TEXT NOT NULL,
    mtime        REAL NOT NULL,
    is_lossy     INTEGER,        -- 0/1, NULL = not probed
    created_at   TEXT NOT NULL
)
```

**Scan-cache schema:**

```sql
CREATE TABLE cache_meta (
    input_signature TEXT NOT NULL,  -- sha256(input|excludes)[:16]
    created_at      TEXT NOT NULL,
    input_path      TEXT NOT NULL,
    excludes        TEXT NOT NULL   -- comma-joined, sorted
);

CREATE TABLE scanned_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path   TEXT NOT NULL UNIQUE,
    file_size     INTEGER NOT NULL,
    mtime         REAL NOT NULL,
    sidecar_files TEXT NOT NULL DEFAULT ''
);
```

The cache filename is `scan_cache_<md5(timestamp)[:12]>_<sig>.db`. The
timestamp portion makes the file unique per run (matching the spec);
the signature portion lets probe verify the cache matches the current
CLI args before trusting it. Pass `--no-scan-cache` to disable the
cache entirely.

---

#### `src/jobs/`

Job list building from discovered audio files.

**Key modules:**
- `builder.py` - Build ConversionJob lists with streaming probe

**Key functions:**
- `enrich_index_rows_streaming()` - Stream-probe files with live progress
- `enrich_index_rows()` - Blocking convenience wrapper
- `build_jobs()` - Build ConversionJob list from discovered files

**Job types:**
| Job Type | Description |
|----------|-------------|
| `convert` | Transcode the source file |
| `copy` | Copy the source file as-is |
| `skip` | Skip the source file |

---

#### `src/execution/`

Conversion execution with thread/process pools. The package is organised as a
small set of single-responsibility modules behind a backward-compatibility
shim (`src.execution.runner`).

**Key modules:**
- `run_all.py` - Top-level orchestrator: dispatches the job list to a
  thread/process pool, returns `(summary, futures, events, write_queue)`
- `run_job.py` - Single-job execution (`copy` / `convert` / `skip` branches)
- `event_drain.py` - Drains queued events into the UI and advances the
  master bar
- `events.py` - `JobEventKind` enum, queue factory, and stream-callback
  helpers
- `runner.py` - Backward-compat shim that re-exports the names above

**Key functions:**
- `run_all()` - Execute jobs using thread or process pool
- `run_job()` - Execute a single `ConversionJob`
- `_drain_events_into_ui()` - Drain queued events to update UI
- `_run_event_drain_thread()` - Long-lived background drain used while
  `run_all` is active

**Event system:**

Workers push events onto a shared queue:
- `STARTED` - Job has begun
- `FINISHED` - Job has completed
- `LOG` - Verbose log line
- `ACTIVITY` - Current activity (copy/convert)

A background drain thread continuously processes these events and updates the UI.

**History writes:**

`run_all` opens a `DBWriteQueue` against the history database and passes it
to each worker. Workers call `write_queue.log_conversion(...)` from inside
`run_job` and return immediately; a single background writer thread drains
the queue and writes rows to SQLite. Callers must call `write_queue.flush()`
after all futures complete so the writer thread exits cleanly before the
DB connection is closed.

---

#### `src/history/`

Conversion history database. The package is organised as a small set of
single-responsibility modules behind a backward-compatibility shim
(`src.history.db`).

**Key modules:**
- `schema.py` - Shared `CREATE TABLE` statement, INSERT OR REPLACE template,
  and WAL/busy-timeout pragmas
- `conversion_db.py` - Synchronous `ConversionDB` wrapper used inside
  workers for resume checks
- `write_queue.py` - `DBWriteQueue` async writer thread that serialises
  history writes from concurrent workers
- `db.py` - Backward-compat shim that re-exports `ConversionDB` and
  `DBWriteQueue`

**Key classes:**
- `ConversionDB` - Wraps a SQLite connection for history reads and the
  resume check
- `DBWriteQueue` - Single background thread that drains queued
  `log_conversion(...)` calls and writes them to SQLite

**Key methods (ConversionDB):**
- `get_record()` - Get history record by source/dest
- `log_conversion()` - Insert or update a history row (also available on
  `DBWriteQueue` for async use)
- `should_skip()` - Check if a job should be skipped based on history

**Resume semantics:**

A job is skippable only if:
1. A matching (source_path, dest_path, job_type) row exists
2. The status is 'SUCCESS'
3. The destination file still exists on disk

**SQLite features:**
- WAL mode for concurrent write access
- 5-second busy timeout
- UNIQUE constraint on (source_path, dest_path)

---

#### `src/audio/`

Audio inspection and lossy detection. The package is organised as a small
set of single-responsibility modules behind a backward-compatibility shim
(`src.audio.inspector`).

**Key modules:**
- `extensions.py` - Tier 1: extension lookup (zero I/O)
- `folder_heuristic.py` - Tier 2: folder-name heuristic (zero I/O)
- `mutagen_probe.py` - Tier 3: mutagen metadata probe (I/O required)
- `cascade.py` - Three-tier single-file cascade (`is_lossy`, `cascade_with_tier`,
  `CascadeTier`)
- `batch.py` - Batch and parallel-future utilities (`probe_many`,
  `probe_generator`, `_classify_by_ext_and_folder`)
- `inspector.py` - Backward-compat shim that re-exports the names above
  (and `MutagenFile`) so existing imports keep working

**Detection cascade:**

1. **Extension lookup** (Tier 1) - Zero I/O, deterministic
   - Unambiguous lossless: `.flac`, `.ape`, `.wv`, `.wav`, etc.
   - Unambiguous lossy: `.mp3`, `.ogg`, `.opus`, `.wma`, etc.
   - Ambiguous: `.m4a`, `.caf` (need Tier 3)

2. **Folder-name heuristic** (Tier 2) - Zero I/O
   - Looks for lossy tokens in parent directory names
   - Tokens: `aac`, `mp3`, `v0`, `128k`, `lame`, `vorbis`, `opus`, `webrip`,
     `itunes`, `amazon`, `deezer`, `spotify`, etc.
   - Stops at fully-numeric directories (e.g. sequential album IDs) and at
     the filesystem root

3. **Mutagen metadata probe** (Tier 3) - I/O required
   - Only for ambiguous extensions
   - Checks codec name in metadata (falls back to `codec_description`)
   - Runs in a thread pool for parallel probing
   - Raises `ProbeError` if mutagen cannot read the file or the codec is
     unknown

---

#### `src/pathing/`

Path resolution and transformation.

**Key modules:**
- `resolver.py` - Path resolution logic

**Key functions:**
- `compute_output_path()` - Compute output path for input file
- `validate_source_path()` - Validate source_path is ancestor of input_path
- `to_wine_path()` - Translate Linux path to Windows path via winepath
- `hide_filename()` - Prefix filename with dot to hide it

---

#### `src/sidecars/`

Sidecar file management.

**Key modules:**
- `manager.py` - Copy lyrics and cover art alongside converted files

**Key functions:**
- `copy_lyrics()` - Copy lyric/text files next to output
- `copy_covers()` - Copy cover art to output directory

**Sidecar patterns:**

Lyrics: `.lrc`, `.txt` (configurable)
Covers: `cover.jpg`, `cover.png`, `folder.jpg`, `albumart.jpg` (configurable)

---

#### `src/ui/`

User interface components.

**Key modules:**
- `progress_view.py` - Rich-based progress display

**Key classes:**
- `RichProgressSink` - Concrete ProgressSink implementation
- `_ProgressRenderer` - Progress bar renderer
- `ProgressSink` (Protocol) - Interface for progress reporting

**Display layout:**

```
[PhaseName N/M files]  ████████░░░░░░░░  83%  ETA 0:32  1.2 GiB
  converting
[dim]log message 1[/dim]
[dim]log message 2[/dim]
...
```

---

## Data Flow

### Normal Conversion Run

```
1. Parse CLI args ──────────────────────────────────────────────────────────────
   │
   ▼
2. Load config files (settings.yaml, presets.yaml)
   │
   ▼
3. Resolve backend (auto-detect or CLI override)
   │
   ▼
4. Validate backend environment (fail-fast)
   │
   ▼
5. Create tmp/index.db (post-probe, deleted on success)
   Also create or reuse tmp/scan_cache_<hash>.db (path-only snapshot,
   kept across runs unless --no-scan-cache is passed).
   │
   ▼
6. Scan phase ──────────────────────────────────────────────────────────────────
   │  Cache hit: load rows from existing scan-cache, skip the walk.
   │  Cache miss: walk the directory with os.scandir, write path+size+
   │  mtime+sidecar_files into the cache as a side-effect of the walk.
   ▼
7. Probe phase ─────────────────────────────────────────────────────────────────
   │  Per-file cascade in a thread pool: each worker walks its file
   │  through extension → folder → mutagen tiers, falling through
   │  to the next tier only when the previous one returns None.
   │  Single "Probing" bar whose label flips (Extension → Folder →
   │  Mutagen) to reflect the mix of tiers resolving in real time.
   │  Writes results to index DB incrementally.
   ▼
8. Lossy gate ─────────────────────────────────────────────────────────────────
   │  If lossy files found and no --lossy-action: abort
   ▼
9. Build ConversionJob list from index
   │
   ▼
10. Execute phase ────────────────────────────────────────────────────────────────
    │  Thread/process pool executes jobs
    │  Each job: verify output, copy sidecars, log to history
    ▼
11. Cleanup phase ────────────────────────────────────────────────────────────────
       Delete tmp/index.db on success
       Preserve tmp/index.db on failure/interrupt
```

### Index-Only Mode (`--build-index`)

```
1-4. Same as above
   │
   ▼
5. Scan + probe phases (same as above)
   │
   ▼
6. Write all rows to user-specified index DB
   │
   ▼
7. Print summary and exit
```

### Index-Run Mode (`--index`)

```
1-4. Same as above
   │
   ▼
5. Open pre-built index DB
   │
   ▼
6. Build ConversionJob list from index rows
   │
   ▼
7-10. Same execute + cleanup phases as above
```

---

## Concurrency Model

### Thread Pool (default)
- Uses `ThreadPoolExecutor` from `concurrent.futures`
- Workers share memory space
- Suitable for I/O-bound tasks like audio conversion
- SQLite connection per worker (WAL mode handles concurrent access)

### Process Pool
- Uses `ProcessPoolExecutor` for CPU isolation
- Each worker gets a copy of arguments
- Uses `multiprocessing.Manager` for cross-process event queue
- Better for CPU-bound conversion work

### Event Queue
- Workers push events: `STARTED`, `FINISHED`, `LOG`, `ACTIVITY`
- A background drain thread continuously processes events
- UI updates happen only in the main thread
- Prevents rich rendering issues from concurrent access

---

## Error Handling

### Fail-Fast Validation
Backend environment is validated immediately on instantiation:
- `NativeFfmpegBackend`: Checks `ffmpeg` binary exists
- `WineDbpowerampBackend`: Checks `wine`, `winepath`, prefix exists, runs smoke test
- `NativeDbpowerampBackend`: Checks `CoreConverter.exe` exists

### Probe Errors
- Mutagen probe failures are caught and treated as "unknown codec"
- Files with unknown codec are treated as lossless
- The conversion backend surfaces the real error during transcoding

### Output Verification
- After every conversion/copy, the output file is verified to exist with non-zero size
- If verification fails, the job is marked as FAILED even if the tool exited 0

### Signal Handling
- SIGINT and SIGTERM handlers mark the run as interrupted
- The index database is preserved for post-mortem debugging
- Original signal handlers are restored in the `finally` block

---

## Extension Points

### Adding a New Backend

1. Create a new class in `src/backends/` extending `ConversionBackend`
2. Implement the four abstract methods: `name()`, `validate_environment()`, `supports()`, `run()`
3. Add the backend to the registry in `src/backends/registry.py`
4. Add to `Backend` enum in `src/models/types.py`

### Adding a New Preset

1. Add a new entry to `presets.yaml` under the `presets:` key
2. Specify the output extension, backend configurations, and sidecar policies
3. The preset will be automatically loaded on next run

### Adding a New Lossy Detection Tier

1. Add a new tier function in `src/audio/inspector.py`
2. Update `is_lossy()` and related functions to call the new tier
3. Consider adding folder-name tokens to `LOSSY_FOLDER_TOKENS` for zero-I/O detection

---

## File Structure

```
wrapper-dbpoweramp/
├── main.py                    # Entry point and orchestrator
├── settings.yaml              # Application configuration
├── presets.yaml              # Encoding preset definitions
├── requirements.txt          # Python dependencies
├── pyproject.toml            # Project metadata
├── src/
│   ├── __init__.py
│   ├── exceptions.py         # Custom exception classes
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── inspector.py      # Backward-compat shim
│   │   ├── extensions.py     # Tier 1: extension lookup
│   │   ├── folder_heuristic.py # Tier 2: folder-name heuristic
│   │   ├── mutagen_probe.py  # Tier 3: mutagen metadata probe
│   │   ├── cascade.py        # Three-tier single-file cascade
│   │   └── batch.py          # Batch / parallel-future utilities
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py           # ConversionBackend ABC
│   │   ├── registry.py       # Backend factory
│   │   ├── native_ffmpeg.py  # FFmpeg backend
│   │   ├── native_dbpoweramp.py  # Native dBpoweramp backend
│   │   └── wine_dbpoweramp.py    # Wine dBpoweramp backend
│   ├── cli/
│   │   ├── __init__.py
│   │   └── args.py           # Argument parsing
│   ├── config/
│   │   ├── __init__.py
│   │   ├── models.py         # settings.yaml dataclasses
│   │   ├── settings_loader.py # settings.yaml loader
│   │   └── preset_loader.py  # presets.yaml loader
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── runner.py         # Backward-compat shim
│   │   ├── events.py         # JobEventKind + queue helpers
│   │   ├── event_drain.py    # UI drain (single + thread)
│   │   ├── run_job.py        # Single-job execution
│   │   └── run_all.py        # Thread/process pool orchestrator
│   ├── history/
│   │   ├── __init__.py
│   │   ├── db.py             # Backward-compat shim
│   │   ├── schema.py         # CREATE TABLE / INSERT / pragmas
│   │   ├── conversion_db.py  # Synchronous read/write wrapper
│   │   └── write_queue.py    # Async writer thread
│   ├── index/
│   │   ├── __init__.py
│   │   ├── scanner.py        # File scanning
│   │   ├── builder.py        # SQLite index (batched writes)
│   │   ├── schema.py         # CREATE TABLE / INSERT / pragmas / migration
│   │   └── cleanup.py        # Index cleanup
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── builder.py        # Backward-compat shim
│   │   ├── classify.py       # job_type decision + IndexRow mutation
│   │   ├── enrich.py         # Streaming + blocking probe pipelines
│   │   └── build_jobs.py     # ConversionJob list construction
│   ├── models/
│   │   ├── __init__.py
│   │   └── types.py          # Dataclass types
│   ├── pathing/
│   │   ├── __init__.py
│   │   └── resolver.py       # Path resolution
│   ├── sidecars/
│   │   ├── __init__.py
│   │   └── manager.py        # Sidecar file copying
│   └── ui/
│       ├── __init__.py
│       ├── progress_view.py  # Backward-compat shim
│       └── progress/
│           ├── protocol.py   # ProgressSink protocol, SubtaskID
│           ├── renderer.py   # Self-contained progress-bar renderer
│           ├── rich_sink.py  # RichProgressSink (rich.live.Live)
│           ├── verbose_sink.py # VerboseProgressSink
│           └── null_sink.py  # NullProgressSink
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Pytest configuration
│   ├── test_lossy_classify.py
│   ├── test_conversion_db.py
│   ├── test_index_builder.py
│   ├── test_mutagen_probe.py
│   ├── test_progress_view.py
│   └── test_dbpoweramp_cli.py
└── docs/                     # This documentation
```
