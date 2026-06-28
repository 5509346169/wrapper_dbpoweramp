# Public API Reference

This document describes the public API surface for programmatic access to the wrapper functionality.

---

## Overview

While this tool is primarily a CLI application, several modules expose programmatic APIs that can be used for scripting or integration with other tools.

---

## Core Modules

### `src.config`

#### Settings Loading

```python
from src.config.settings_loader import load_settings
from pathlib import Path

# Load settings from file
settings = load_settings(Path("settings.yaml"))
```

#### Preset Loading

```python
from src.config.preset_loader import load_presets, get_preset

# Load all presets
presets = load_presets(Path("presets.yaml"))

# Get specific preset
preset = get_preset(presets, "flac-lossless")
```

### `src.models.types`

#### Data Types

```python
from src.models.types import (
    Backend,
    LossyAction,
    JobType,
    JobStatus,
    ConversionJob,
    JobResult,
    PresetConfig,
    SidecarPolicy,
    CoverPolicy,
    AUDIO_EXTENSIONS,
)
```

#### Backend Enum

```python
# Available backends
Backend.NATIVE_FFMPEG    # FFmpeg encoder
Backend.NATIVE_DBPOWERAMP # Native dBpoweramp on Windows
Backend.WINE_DBPOWERAMP   # dBpoweramp via Wine
```

#### Lossy Action Enum

```python
LossyAction.LEAVE   # Skip lossy files
LossyAction.COPY    # Copy lossy files as-is
LossyAction.CONVERT # Transcode lossy files
```

#### Job Status Types

```python
# Literal types
JobType = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
```

#### Audio Extensions

```python
# Set of supported audio extensions
AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".ape", ".wv", ".tta"}
```

---

## Backend API

### Creating Backends

```python
from src.backends.registry import get_backend
from src.models.types import Backend

# Get backend instance
backend = get_backend(Backend.NATIVE_FFMPEG, settings)

# Validate environment
backend.validate_environment()

# Check preset support
if backend.supports(preset):
    print("Preset is supported")
```

### Running Conversions

```python
from src.models.types import ConversionJob

# Create a job
job = ConversionJob(
    infile=Path("input.flac"),
    outfile=Path("output.mp3"),
    preset=preset,
    job_type="convert",
)

# Run conversion
result = backend.run(job, stream_callback=None)

# Check result
if result.status == "SUCCESS":
    print("Conversion succeeded")
elif result.status == "FAILED":
    print(f"Failed: {result.error_msg}")
```

### Stream Callback

```python
def my_callback(line: str) -> None:
    print(f"[VERBOSE] {line}")

result = backend.run(job, stream_callback=my_callback)
```

---

## Index API

### Building Index

```python
from src.index.builder import IndexBuilder
from src.index.scanner import scan_with_progress, IndexRow

# Create index
index = IndexBuilder(Path("my_index.db"))

# Scan files
rows, sidecar_map = scan_with_progress(
    input_path=Path("."),
    excludes=[],
    preset=preset,
    progress=None,  # Or use RichProgressSink()
)

# Add rows to index
for row in rows:
    index.add(row)

# Commit and close
index.commit()
index.close()
```

### Reading Index

```python
from src.index.builder import IndexBuilder

# Open existing index
index = IndexBuilder.from_existing(Path("my_index.db"))

# Iterate rows
for row in index.iter_rows():
    print(f"Source: {row.source_path}")
    print(f"Dest: {row.dest_path}")
    print(f"Job type: {row.job_type}")
    print(f"Lossy: {row.is_lossy}")

# Get summary
summary = index.get_summary()
print(f"Total: {summary['total']}")
print(f"Lossy: {summary['lossy']}")
print(f"By type: {summary['by_type']}")

index.close()
```

### Index Schema

```sql
CREATE TABLE index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    dest_path TEXT NOT NULL,
    job_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    sidecar_files TEXT NOT NULL,
    mtime REAL NOT NULL,
    is_lossy INTEGER,        -- 0/1, NULL = not probed
    created_at TEXT NOT NULL
)
```

---

## History API

### Opening Database

```python
from src.history.db import ConversionDB

db = ConversionDB(Path("conversion_history.db"))
```

### DB Version Inspection

```python
from src.history.migrations import get_db_version
from pathlib import Path

info = get_db_version(Path("conversion_history.db"))
print(info)
# History DB:    conversion_history.db
# Schema:        v2 (up-to-date)
# Target:        v2
# Last migrated: 2026-06-28 14:30:00 UTC
# ...
```

`get_db_version` is read-only — it opens the DB with `mode=ro` and never migrates or writes. Use `migrate_to_current()` (in the same module) to apply pending migrations.

### Logging Conversions

```python
db.log_conversion(
    source=str(input_path),
    dest=str(output_path),
    job_type="convert",
    command=None,
    status="SUCCESS",
    error_msg=None,
    stdout=None,
    # Optional verify columns (writes NULL if omitted):
    verify_status="OK",
    verify_reason=None,
    verify_format="FLAC/PCM_16",
    verify_duration_s=3.42,
)
```

### Checking Resume

```python
# Check if should skip
should_skip = db.should_skip(
    source=str(input_path),
    dest=str(output_path),
    job_type="convert",
    dest_file_exists=True,
)

if should_skip:
    print("Already converted, skipping")
else:
    print("Not yet converted, processing")
```

### Getting Records

```python
record = db.get_record(source=str(input_path), dest=str(output_path))

if record:
    print(f"Status: {record['status']}")
    print(f"Timestamp: {record['timestamp']}")
else:
    print("No record found")
```

### Closing

```python
db.close()
```

---

## Audio Inspection API

### Lossy Detection

```python
from src.audio.inspector import is_lossy, probe_many
from pathlib import Path

# Single file
is_lossy_file = is_lossy(Path("track.mp3"))
print(f"Track is lossy: {is_lossy_file}")

# Multiple files with parallel probing
files = [
    Path("track1.flac"),
    Path("track2.mp3"),
    Path("track3.m4a"),
]
results = probe_many(files, workers=4)

for path, is_lossy in results.items():
    print(f"{path}: {'lossy' if is_lossy else 'lossless'}")
```

### Detection Tiers

```python
from src.audio.inspector import (
    _is_lossy_by_ext,
    _is_lossy_by_folder,
    _is_lossy_by_mutagen,
)

# Tier 1: Extension only (fast, no I/O)
result = _is_lossy_by_ext(Path("track.mp3"))  # True
result = _is_lossy_by_ext(Path("track.flac"))  # False
result = _is_lossy_by_ext(Path("track.m4a"))  # None (ambiguous)

# Tier 2: Folder-name heuristic (fast, no I/O)
result = _is_lossy_by_folder(Path("~/Music/[320Kbps]/track.mp3"))  # True

# Tier 3: Mutagen probe (slower, I/O required)
result = _is_lossy_by_mutagen(Path("track.m4a"))  # True or False
```

---

## Integrity Verification API

### verify_file

```python
from src.audio.integrity import verify_file, VerifyStatus, VerifyResult

result = verify_file(Path("output.flac"))
# result is a VerifyResult:
#   result.status  -> VerifyStatus.OK | NOT_OK | UNSUPPORTED
#   result.reason -> str or None
#   result.fmt    -> str or None  (e.g. "FLAC/PCM_16")
#   result.duration_s -> float or None
#   result.short  -> "Okay" | "Not - <reason>" | "Skipped - <reason>"
```

The three backends are tried in priority order: `soundfile` (libsndfile full-frame decode, FLAC MD5 verification, truncation guard) -> `miniaudio` (streaming decode) -> `mutagen` (tag sanity only). If no backend claims the file extension or none is installed, returns `UNSUPPORTED`.

## Path Resolution API

### Computing Output Paths

```python
from src.pathing.resolver import compute_output_path
from pathlib import Path

# Standard behavior (input_root is the base)
output = compute_output_path(
    infile=Path("/home/user/Music/Artist/Album/track.flac"),
    input_root=Path("/home/user/Music"),
    source_root=None,
    output_root=Path("/home/converted"),
    target_ext=".mp3",
)
# Result: /home/converted/Artist/Album/track.mp3

# With source_root (preserves library structure)
output = compute_output_path(
    infile=Path("/home/user/Music/Artist/Album/track.flac"),
    input_root=Path("/home/user/Music/Artist/Album"),
    source_root=Path("/home/user/Music"),
    output_root=Path("/home/converted"),
    target_ext=".mp3",
)
# Result: /home/converted/Artist/Album/track.mp3
```

### Wine Path Translation

```python
from src.pathing.resolver import to_wine_path

# Translate Linux path to Windows path for Wine
wine_path = to_wine_path(
    linux_path=Path("/home/user/Music/track.flac"),
    wine_binary="wine",
    wine_prefix="~/.wine-dbpoweramp",
    winepath_binary="winepath",
)
# Result: Z:\home\user\Music\track.flac
```

### Filename Hiding

```python
from src.pathing.resolver import hide_filename

# Add dot prefix to hide files
hidden = hide_filename("cover.jpg")  # .cover.jpg
hidden = hide_filename(".cover.jpg")  # .cover.jpg (unchanged)
```

---

## Sidecar Management API

### Copying Lyrics

```python
from src.sidecars.manager import copy_lyrics
from src.models.types import SidecarPolicy
from pathlib import Path

policy = SidecarPolicy(
    copy=True,
    extensions=[".lrc", ".txt"],
    hide=False,
)

copied = copy_lyrics(
    infile=Path("track.flac"),
    outfile=Path("output/track.mp3"),
    policy=policy,
)
# Copies track.lrc and/or track.txt next to track.mp3
```

### Copying Covers

```python
from src.sidecars.manager import copy_covers
from src.models.types import CoverPolicy

policy = CoverPolicy(
    copy=True,
    patterns=["cover.jpg", "cover.png", "folder.jpg"],
    hide=True,  # Prefix with dot
)

copied = copy_covers(
    infile=Path("track.flac"),
    outfile=Path("output/track.mp3"),
    policy=policy,
)
# Copies cover.jpg as .cover.jpg next to track.mp3
```

---

## Progress Reporting API

### Progress Sink Protocol

```python
from src.ui.progress_view import ProgressSink, RichProgressSink, SubtaskID

# Create sink
sink = RichProgressSink(total_bytes=1024000)

# Start phase
sink.start_phase("Converting", total=100)

# Update progress
sink.advance(5)

# Start subtask
task_id = sink.start_subtask("track01.flac")

# Update activity
sink.set_activity("converting")

# Log message
sink.log("Starting conversion...")

# Finish subtask
sink.finish_subtask(task_id)

# Stop
sink.stop()
```

### Custom Implementation

```python
from src.ui.progress_view import ProgressSink, SubtaskID

class MyProgressSink:
    """Custom progress implementation."""
    
    def start_phase(self, name: str, total: int) -> None:
        print(f"Starting {name} (total: {total})")
    
    def advance(self, amount: int = 1) -> None:
        self._count = getattr(self, '_count', 0) + amount
        print(f"Progress: {self._count}")
    
    def start_subtask(self, name: str) -> SubtaskID:
        print(f"Starting subtask: {name}")
        return SubtaskID(id=0)
    
    def finish_subtask(self, subtask_id: SubtaskID) -> None:
        print("Subtask finished")
    
    def log(self, message: str) -> None:
        print(f"[LOG] {message}")
    
    def stop(self) -> None:
        print("Progress stopped")
    
    def stop_phase(self) -> None:
        print("Phase stopped")
    
    def set_activity(self, activity: str) -> None:
        print(f"Activity: {activity}")
```

---

## Job Execution API

### Running Jobs

```python
from src.execution.runner import run_all, run_job
from src.history.db import ConversionDB

# Open history database
db = ConversionDB(Path("history.db"))

# Run all jobs
summary, futures, events = run_all(
    jobs=job_list,
    backend=backend,
    db=db,
    force=False,
    workers=4,
    worker_model="thread",
    verbose=False,
    progress=sink,
)

print(f"Success: {summary['success']}")
print(f"Skipped: {summary['skipped']}")
print(f"Failed: {summary['failed']}")

# Or run a single job
status, filename, error = run_job(
    job=job,
    backend=backend,
    db_path=str(db.db_path),
    force=False,
    stream_callback=None,
)
```

---

## Exception Classes

### Configuration Errors

```python
from src.exceptions import ConfigError, PresetNotFoundError

try:
    preset = get_preset(presets, "invalid-preset")
except PresetNotFoundError as e:
    print(f"Available presets: {e.available}")

try:
    settings = load_settings(Path("invalid.yaml"))
except ConfigError as e:
    print(f"Config error: {e}")
```

### Backend Errors

```python
from src.exceptions import BackendError

try:
    backend = get_backend(Backend.WINE_DBPOWERAMP, settings)
    backend.validate_environment()
except BackendError as e:
    print(f"Backend error: {e}")
```

### Probe Errors

```python
from src.exceptions import ProbeError

try:
    is_lossy = _is_lossy_by_mutagen(Path("invalid.mp3"))
except ProbeError as e:
    print(f"Probe error for {e.file}: {e.stderr}")
```

---

## Example: Complete Programmatic Run

```python
#!/usr/bin/env python3
"""Example: Programmatic conversion using the wrapper API."""

from pathlib import Path
from src.config.settings_loader import load_settings
from src.config.preset_loader import load_presets, get_preset
from src.backends.registry import get_backend
from src.models.types import Backend, LossyAction
from src.jobs.builder import enrich_index_rows_streaming
from src.execution.runner import run_all
from src.history.db import ConversionDB
from src.index.scanner import scan_with_progress
from src.index.builder import IndexBuilder

def convert_directory(
    input_dir: Path,
    output_dir: Path,
    preset_name: str,
    backend_name: Backend = Backend.NATIVE_FFMPEG,
):
    """Convert all audio files in a directory."""
    
    # 1. Load config
    settings = load_settings(Path("settings.yaml"))
    presets = load_presets(Path("presets.yaml"))
    preset = get_preset(presets, preset_name)
    
    # 2. Get backend
    backend = get_backend(backend_name, settings)
    
    # 3. Scan files
    rows, _ = scan_with_progress(
        input_path=input_dir,
        excludes=[],
        preset=preset,
        progress=None,
    )
    
    # 4. Enrich with probing
    enrich_index_rows_streaming(
        scan_rows=rows,
        input_root=input_dir,
        source_root=None,
        output_root=output_dir,
        preset=preset,
        lossy_action=LossyAction.CONVERT,
        no_lossy_check=False,
        probe_workers=4,
        progress=None,
        index_builder=None,
    )
    
    # 5. Build jobs
    from src.models.types import ConversionJob
    jobs = [
        ConversionJob(
            infile=Path(row.source_path),
            outfile=Path(row.dest_path),
            preset=preset,
            job_type=row.job_type,
        )
        for row in rows
        if row.job_type != "skip"
    ]
    
    # 6. Execute
    db = ConversionDB(Path("history.db"))
    summary, _, _ = run_all(
        jobs=jobs,
        backend=backend,
        db=db,
        force=False,
        workers=4,
        worker_model="thread",
        verbose=False,
        progress=None,
    )
    db.close()
    
    return summary

# Usage
if __name__ == "__main__":
    results = convert_directory(
        input_dir=Path("./music"),
        output_dir=Path("./converted"),
        preset_name="mp3-v0-vbr",
    )
    print(f"Converted: {results['success']}")
```

---

## App Context API

### build_context

```python
from src.app.context import build_context
from src.cli.args import parse_args

args = parse_args()
ctx = build_context(args)

# ctx is an AppContext frozen dataclass with:
#   ctx.args, ctx.settings, ctx.preset, ctx.backend, ctx.backend_name,
#   ctx.db_path, ctx.workers, ctx.worker_model, ctx.execution_mode, ctx.verbose
```

`build_context` resolves the backend name, loads settings and presets, validates preset/backend compatibility, and populates all fields. Raises `SystemExit` on validation failure.

## Constants Reference

### Audio Extensions

```python
AUDIO_EXTENSIONS = {
    ".flac", ".mp3", ".m4a", ".opus", ".ogg",
    ".wav", ".ape", ".wv", ".tta"
}
```

### Lossless Codecs (for mutagen detection)

```python
LOSSLESS_CODECS = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "shorten", "als", "g711", "g711a", "g711u",
}
```

### Lossy Folder Tokens

```python
LOSSY_FOLDER_TOKENS = {
    "aac", "mp3", "v0", "v2",
    "128k", "192k", "256k", "320k",
    "128kbps", "192kbps", "256kbps", "320kbps",
    "lame", "l3tag", "ogg", "vorbis", "opus",
    "webrip", "shoprip", "itunes", "amazon",
    "deezer", "spotify", "tidal", "qobuz", "lossy",
}
```
