---
permalink: /api/
layout: reference
title: Public API Reference
slug: api
category: reference
order: 10
summary: Programmatic entry points for scripting and integration.
audience: [engineer]
---

This document describes the public API surface for programmatic access to the wrapper functionality.

## Overview

While this tool is primarily a CLI application, several modules expose programmatic APIs that can be used for scripting or integration with other tools.

## Core modules

### `src.config`

#### Settings loading

```python
from src.config.settings_loader import load_settings
from pathlib import Path

settings = load_settings(Path("settings.yaml"))
```

#### Preset loading

```python
from src.config.preset_loader import load_presets, get_preset

presets = load_presets(Path("presets.yaml"))
preset = get_preset(presets, "flac-lossless")
```

### `src.models.types`

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

#### Backend enum

```python
Backend.NATIVE_FFMPEG     # FFmpeg encoder
Backend.NATIVE_DBPOWERAMP # Native dBpoweramp on Windows
Backend.WINE_DBPOWERAMP   # dBpoweramp via Wine
```

#### Lossy action enum

```python
LossyAction.LEAVE   # Skip lossy files
LossyAction.COPY    # Copy lossy files as-is
LossyAction.CONVERT # Transcode lossy files
```

#### Job status types

```python
JobType   = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
```

#### Audio extensions

```python
AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".ape", ".wv", ".tta"}
```

## Backend API

### Creating backends

```python
from src.backends.registry import get_backend
from src.models.types import Backend

backend = get_backend(Backend.NATIVE_FFMPEG, settings)
backend.validate_environment()

if backend.supports(preset):
    print("Preset is supported")
```

### Running conversions

```python
from src.models.types import ConversionJob

job = ConversionJob(
    infile=Path("input.flac"),
    outfile=Path("output.mp3"),
    preset=preset,
    job_type="convert",
)

result = backend.run(job, stream_callback=None)

if result.status == "SUCCESS":
    print("Conversion succeeded")
elif result.status == "FAILED":
    print(f"Failed: {result.error_msg}")
```

### Stream callback

```python
def my_callback(line: str) -> None:
    print(f"[VERBOSE] {line}")

result = backend.run(job, stream_callback=my_callback)
```

## Index API

### Building index

```python
from src.index.builder import IndexBuilder
from src.index.scanner import scan_with_progress, IndexRow

index = IndexBuilder(Path("my_index.db"))

rows, sidecar_map = scan_with_progress(
    input_path=Path("."),
    excludes=[],
    preset=preset,
    progress=None,
)

for row in rows:
    index.add(row)

index.commit()
index.close()
```

### Reading index

```python
from src.index.builder import IndexBuilder

index = IndexBuilder.from_existing(Path("my_index.db"))

for row in index.iter_rows():
    print(f"Source: {row.source_path}")
    print(f"Dest: {row.dest_path}")
    print(f"Job type: {row.job_type}")
    print(f"Lossy: {row.is_lossy}")

summary = index.get_summary()
print(f"Total: {summary['total']}")
print(f"Lossy: {summary['lossy']}")
print(f"By type: {summary['by_type']}")

index.close()
```

### Index schema

```sql
CREATE TABLE index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    dest_path TEXT NOT NULL,
    job_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    sidecar_files TEXT NOT NULL,
    mtime REAL NOT NULL,
    is_lossy INTEGER,
    created_at TEXT NOT NULL
)
```

## History API

### Opening database

```python
from src.history.db import ConversionDB

db = ConversionDB(Path("conversion_history.db"))
```

### DB version inspection

```python
from src.history.migrations import get_db_version
from pathlib import Path

info = get_db_version(Path("conversion_history.db"))
```

`get_db_version` is read-only — it opens the DB with `mode=ro` and never migrates or writes. Use `migrate_to_current()` (in the same module) to apply pending migrations.

### Logging conversions

```python
db.log_conversion(
    source=str(input_path),
    dest=str(output_path),
    job_type="convert",
    command=None,
    status="SUCCESS",
    error_msg=None,
    stdout=None,
    verify_status="OK",
    verify_reason=None,
    verify_format="FLAC/PCM_16",
    verify_duration_s=3.42,
)
```

### Checking resume

```python
should_skip = db.should_skip(
    source=str(input_path),
    dest=str(output_path),
    job_type="convert",
    dest_file_exists=True,
    dest_file_size=stat_result.st_size,
)
```

### Inspecting history

```python
for record in db.iter_records():
    print(f"{record['source']} -> {record['dest']}: {record['status']}")
```

## Audio API

### Lossy detection (single file)

```python
from src.audio.inspector import is_lossy

if is_lossy(Path("track.mp3")):
    print("Lossy")
```

### Lossy detection (batch)

```python
from src.audio.inspector import probe_many

results = probe_many([Path(p) for p in file_paths], workers=8)
# {Path("track01.flac"): False, Path("track03.mp3"): True, ...}
```

### Integrity verification

```python
from src.audio.integrity import verify_file

result = verify_file(Path("output.flac"))
print(result.short)   # "Okay" | "Not - <reason>" | "Skipped - <reason>"

if result.status.name == "NOT_OK":
    print(f"Corrupt output: {result.reason}")
```

## Pathing API

### Output path computation

```python
from src.pathing.resolver import compute_output_path

out = compute_output_path(
    infile=Path("Music/Artist/Album/track.flac"),
    input_root=Path("Music"),
    source_root=None,
    output_root=Path("Converted"),
    target_ext=".mp3",
)
# Path("Converted/Artist/Album/track.mp3")
```

### Wine path translation

```python
from src.pathing.resolver import to_wine_path

wine_path = to_wine_path(
    linux_path=Path("/home/user/Music/song.wav"),
    wine_binary="wine",
    wine_prefix="~/.wine-dbpoweramp",
    winepath_binary="winepath",
)
# "Z:\\home\\user\\Music\\song.wav"
```

## Sidecar API

```python
from src.sidecars.manager import copy_lyrics, copy_covers

written = copy_lyrics(infile, outfile, preset.lyrics)
written += copy_covers(infile, outfile, preset.covers)
```

## Progress API

### Null sink

```python
from src.ui.progress_view import NullProgressSink

sink = NullProgressSink()
```

### Verbose sink

```python
from src.ui.progress_view import VerboseProgressSink

sink = VerboseProgressSink()
sink.start_phase("Scanning", total=156)
for i in range(156):
    sink.advance()
sink.stop_phase()
```

### Rich sink

```python
from src.ui.progress_view import RichProgressSink

sink = RichProgressSink(total_files=156, total_bytes=2_500_000_000)
sink.start_phase("Converting", total=156)
# ... feed events from workers ...
sink.stop_phase()
sink.stop()
```

## CLI entry points

The CLI is exposed as a Python module:

```python
from src.cli.args import parse_args, validate_args
from src.app.commands.run_pipeline import cmd_run_pipeline
from src.app.context import build_context

args = parse_args(["-I", "~/Music", "-O", "~/Converted", "-p", "flac-lossless"])
validate_args(args)
ctx = build_context(args)
cmd_run_pipeline(ctx)
```

## Complete example

Convert a directory programmatically:

```python
from pathlib import Path
from src.config.settings_loader import load_settings
from src.config.preset_loader import load_presets, get_preset
from src.backends.registry import get_backend
from src.models.types import Backend

settings = load_settings(Path("settings.yaml"))
presets = load_presets(Path("presets.yaml"))
preset = get_preset(presets, "flac-lossless")

backend = get_backend(Backend.NATIVE_FFMPEG, settings)
backend.validate_environment()

if not backend.supports(preset):
    raise SystemExit(f"Backend does not support preset '{preset.name}'")

# ... build jobs, run via run_all, etc.
```
