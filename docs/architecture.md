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
  probe_workers: 8
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
- `scanner.py` - File tree scanner with optional progress bar
- `builder.py` - SQLite index database manager
- `cleanup.py` - Index cleanup utilities

**Key classes:**
- `IndexRow` - A row in the temp index snapshot
- `IndexBuilder` - Manages the index_entries SQLite table

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

Conversion execution with thread/process pools.

**Key modules:**
- `runner.py` - Execute ConversionJob lists using the configured backend

**Key functions:**
- `run_all()` - Execute jobs using thread or process pool
- `run_job()` - Execute a single ConversionJob
- `_drain_events_into_ui()` - Drain queued events to update UI

**Event system:**

Workers push events onto a shared queue:
- `STARTED` - Job has begun
- `FINISHED` - Job has completed
- `LOG` - Verbose log line
- `ACTIVITY` - Current activity (copy/convert)

A background drain thread continuously processes these events and updates the UI.

---

#### `src/history/`

Conversion history database.

**Key modules:**
- `db.py` - SQLite history database wrapper

**Key classes:**
- `ConversionDB` - Wraps SQLite connection for history tracking

**Key methods:**
- `get_record()` - Get history record by source/dest
- `log_conversion()` - Insert or update a history row
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

Audio inspection and lossy detection.

**Key modules:**
- `inspector.py` - Multi-tier lossy detection

**Detection cascade:**

1. **Extension lookup** (Tier 1) - Zero I/O, deterministic
   - Unambiguous lossless: `.flac`, `.ape`, `.wv`, `.wav`, etc.
   - Unambiguous lossy: `.mp3`, `.ogg`, `.opus`, `.wma`, etc.
   - Ambiguous: `.m4a`, `.mp4`, `.caf` (need Tier 3)

2. **Folder-name heuristic** (Tier 2) - Zero I/O
   - Looks for lossy tokens in parent directory names
   - Tokens: `aac`, `mp3`, `v0`, `128k`, `lame`, `vorbis`, `opus`, `webrip`, `itunes`, `amazon`, `deezer`, `spotify`, etc.

3. **Mutagen metadata probe** (Tier 3) - I/O required
   - Only for ambiguous extensions
   - Checks codec name in metadata
   - Runs in thread pool for parallel probing

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
5. Create tmp/index.db
   │
   ▼
6. Scan phase ──────────────────────────────────────────────────────────────────
   │  Discovers audio files, collects stats and sidecar candidates
   ▼
7. Probe phase ─────────────────────────────────────────────────────────────────
   │  Multi-tier lossy detection (extension, folder heuristic, mutagen)
   │  Writes results to index DB incrementally
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
│   │   └── inspector.py      # Multi-tier lossy detection
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
│   │   ├── settings_loader.py # settings.yaml loader
│   │   └── preset_loader.py  # presets.yaml loader
│   ├── execution/
│   │   ├── __init__.py
│   │   └── runner.py         # Job execution
│   ├── history/
│   │   ├── __init__.py
│   │   └── db.py             # SQLite history
│   ├── index/
│   │   ├── __init__.py
│   │   ├── scanner.py        # File scanning
│   │   ├── builder.py       # Index DB manager
│   │   └── cleanup.py        # Index cleanup
│   ├── jobs/
│   │   ├── __init__.py
│   │   └── builder.py        # Job list building
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
│       └── progress_view.py  # Rich progress display
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Pytest configuration
│   ├── test_lossy_classify.py
│   ├── test_conversion_db.py
│   ├── test_index_builder.py
│   ├── test_mutagen_probe.py
│   └── test_progress_view.py
└── docs/                     # This documentation
```
