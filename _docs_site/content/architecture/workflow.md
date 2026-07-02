---
title: Workflow
summary: Phases of a conversion run from CLI parse to cleanup.
audience: [engineer]
weight: 20
---

This document describes how a conversion run flows from start to finish, including all phases and decision points.

## Overview

A conversion run goes through several distinct phases:

1. **Initialization** — parse args, load config, resolve backend
2. **Scanning** — discover audio files in the input path
3. **Probing** — classify files as lossy/lossless
4. **Gate check** — verify lossy action policy is set
5. **Execution** — run conversions in parallel
6. **Cleanup** — clean up temporary files

## Phase 1: initialization

### 1.1 Parse command-line arguments

```python
args = parse_args()
validate_args(args)
```

Validates:

- `--source-path` is an ancestor of `--input`
- `--lossy-action` and `--no-lossy-check` are not both set
- `--dry-run` and `--lossy-action` are not both set
- `--index` and `--build-index` are not both set
- `--index` file exists (if specified)
- `--build-index` parent directory exists (if specified)

### 1.2 Load configuration

```python
settings = load_settings(Path("settings.yaml"))
presets = load_presets(Path("presets.yaml"))
```

### 1.3 Resolve preset

```python
preset = get_preset(presets, args.preset)
```

Raises `PresetNotFoundError` if preset not found.

### 1.4 Resolve backend

```python
backend_name = detect_backend_for_run(
    cli_backend=cli_backend,
    settings=settings,
    preset=preset,
    platform=sys.platform,
    auto_detect_override=args.auto_detect_backend,
)
backend = get_backend(backend_name, settings)
```

Resolution order:

1. CLI `--backend` flag wins
2. Auto-detect on Windows with dBpoweramp
3. `backend.default` from settings

### 1.5 Validate preset compatibility

```python
if not backend.supports(preset):
    print(f"error: backend '{backend_name}' does not support preset '{preset.name}'.")
    sys.exit(1)
```

### 1.6 Validate backend environment (fail-fast)

```python
backend.validate_environment()
```

For `NativeFfmpegBackend`: checks `ffmpeg` binary exists.
For `WineDbpowerampBackend`: checks `wine`, `winepath`, prefix exists, smoke test.
For `NativeDbpowerampBackend`: checks `CoreConverter.exe` exists.

Raises `BackendError` with actionable message if validation fails.

## Phase 2: scanning

### 2.1 Discover audio files

```python
audio_files = _discover_audio_files(args.input, args.exclude)
```

Behaviour:

- If `--input` is a file, returns that file
- If `--input` is a directory, recursively finds all files matching `AUDIO_EXTENSIONS`
- Skips directories in `--exclude` list
- Returns sorted list of `Path` objects

### 2.2 Scan with progress

```python
rows, sidecar_map = scan_with_progress(
    input_path=args.input,
    excludes=args.exclude,
    preset=preset,
    progress=sink,
)
```

For each file:

1. Collect file stats (size, mtime)
2. Find existing sidecar files (lyrics, covers)
3. Advance progress bar

Output: list of `IndexRow` objects with `source_path`, `file_size`, `sidecar_files`, `mtime` set.

## Phase 3: probing

### 3.1 Determine path roots

```python
if args.input.is_file():
    input_root = args.input.parent
else:
    input_root = args.input

source_root = args.source_path if args.source_path is not None else None
```

### 3.2 Create temporary index database

```python
index_db_path = Path("tmp/index.db")
index_builder = IndexBuilder(index_db_path)
```

The database is created before the scan so it captures every file, including those the lossy gate may skip.

### 3.3 Stream-probe files

```python
lossy_files_found = enrich_index_rows_streaming(
    scan_rows=rows,
    input_root=input_root,
    source_root=source_root,
    output_root=args.output,
    preset=preset,
    lossy_action=lossy_action,
    no_lossy_check=args.no_lossy_check,
    probe_workers=settings.execution.probe_workers,
    progress=sink,
    index_builder=index_builder,
)
```

**Detection cascade:**

| Tier | Method | I/O required | When used |
|------|--------|--------------|-----------|
| 1 | Extension lookup | No | Always |
| 2 | Folder-name heuristic | No | When extension is unambiguous |
| 3 | Mutagen metadata | Yes | Only for ambiguous extensions (`.m4a`, `.mp4`, `.caf`) |

For each file:

1. Try extension lookup
2. If ambiguous, try folder-name heuristic
3. If still unknown, run mutagen probe (in thread pool)
4. Determine `job_type` based on lossy action policy
5. Compute output path
6. Write to index database

**Job type determination:**

| is_lossy | lossy_action | job_type |
|----------|--------------|----------|
| False | any | `convert` |
| True | None | `skip` |
| True | `leave` | `skip` |
| True | `copy` | `copy` |
| True | `convert` | `convert` |

### 3.4 Commit index

```python
index_builder.commit()
```

## Phase 4: gate check

### 4.1 Check for lossy files

```python
if (
    lossy_files_found
    and args.lossy_action is None
    and not args.dry_run
    and not args.list_lossy
    and not args.no_lossy_check
):
    print("Lossy source files found. You must specify --lossy-action to proceed.")
    sys.exit(1)
```

If lossy files found and no policy:

1. Print error message with list of lossy files
2. Exit with code 1

### 4.2 Handle inspection modes

#### `--list-lossy`

```python
if args.list_lossy:
    for f in lossy_files_found:
        print(f)
    return
```

#### `--dry-run`

```python
if args.dry_run:
    print("Dry run — jobs that would be executed:")
    for job in jobs:
        print(f"  {job.infile} -> {job.outfile}  [{job.job_type}]")
    return
```

## Phase 5: execution

### 5.1 Open history database

```python
db = ConversionDB(Path(settings.history.db_path))
```

### 5.2 Create job list

```python
def _row_to_job(row: IndexRow) -> ConversionJob:
    return ConversionJob(
        infile=Path(row.source_path),
        outfile=Path(row.dest_path),
        preset=preset,
        job_type=row.job_type,
        is_lossy_source=row.is_lossy,
        reason=reason,
    )

jobs = [_row_to_job(r) for r in source_rows]
```

### 5.3 Execute jobs

```python
summary, futures, events, write_queue = run_all(
    jobs=jobs,
    backend=backend,
    db_path=str(db_path),
    force=args.force,
    workers=workers,
    worker_model=worker_model,
    verbose=args.verbose,
    progress=sink,
    print_to_terminal=args.verbose,
)
```

Execution flow:

1. `run_all()` creates a `DBWriteQueue` for async history writes
2. A background drain thread starts to continuously process UI events
3. Workers submit jobs to the thread/process pool
4. Each worker:
   - Opens its own `ConversionDB` connection for resume checks
   - Pushes events (`STARTED`, `ACTIVITY`, `FINISHED`) to the shared queue
   - For conversions/copies, queues history logs via `DBWriteQueue`

For each job:

1. **Skip jobs** — skip silently, don't count against history
2. **Copy jobs** — create output directory, copy file with metadata, verify output, copy sidecars, queue history log
3. **Convert jobs** — check resume eligibility, create output directory, run backend conversion, verify output, copy sidecars, queue history log

### 5.4 Resume check

```python
dest_exists = job.outfile.exists()
dest_size = job.outfile.stat().st_size if dest_exists else None
if not force and db.should_skip(
    str(job.infile), str(job.outfile),
    job_type=job.job_type,
    dest_file_exists=dest_exists,
    dest_file_size=dest_size,
):
    status = "SKIPPED"
```

Skip criteria:

- History record exists with matching source, dest, job_type
- Status is `SUCCESS`
- Destination file still exists
- (Optional) Stored file size matches current file size

When `--verify-skip` is set, the on-disk output is re-decoded via `src.audio.integrity.verify_file()` before honouring the history row.

### 5.5 Output verification

For `convert` jobs: `run_job` calls `_verify_output_file(job)`, which runs a full-frame decode via `src.audio.integrity.verify_file()` (soundfile → miniaudio → mutagen). For `copy` jobs: existence + non-zero size only. For `skip` jobs: `_verify_output_file` is not called inside `run_job` (no output file).

A `VERIFY_RESULT` event is enqueued before the `FINISHED` event, giving the progress sink real-time feedback for both `--execution-mode hybrid` and `--execution-mode phased`.

Outcomes:

- `NOT_OK` — job is flipped to `FAILED`; history row receives `verify_status="NOT_OK"` and `verify_reason="Not - <reason>"`
- `UNSUPPORTED` — job passes; `error_msg` receives `verify skipped: <reason>` (soft warning, not a failure)
- `OK` — job passes with no extra annotation

### 5.6 Sidecar copying

```python
copy_lyrics(infile, outfile, preset.lyrics)
copy_covers(infile, outfile, preset.covers)
```

- **Lyrics:** copied with same extension (`.lrc`, `.txt`)
- **Covers:** copied with hidden name (`.cover.jpg`) if policy says to hide

## §7a: pre-verify skip gate

When `--verify-skip` is set, the pipeline re-decodes each skip-candidate's on-disk output before honouring the history row:

```python
pre = verify_file(job.outfile)
if pre.status is VerifyStatus.NOT_OK:
    pending_jobs.append(job)
    skipped_jobs.remove(job)
    continue
elif pre.status is VerifyStatus.OK:
    pass  # fall through to normal skip
# UNSUPPORTED: also trust the existing row
```

**Demotion policy:**

- `OK` → respect the existing `should_skip` decision (fast path, no reconvert)
- `NOT_OK` → demote from skip to pending. The bad `SUCCESS` row is overwritten by the new run's `log_conversion`
- `UNSUPPORTED` → trust the existing row (can't decode it, so don't penalise)

The demotion is visible in the UI via a `VERIFY_RESULT` event with `status=NOT_OK` before the conversion phase starts.

This pre-filter runs before the `phased` / `hybrid` split, so the demotion logic is identical in both `--execution-mode hybrid` and `--execution-mode phased`.

## Phase 6: cleanup

### 6.1 Print summary

```
Done.  Success: 42  Skipped: 3  Failed: 1
```

### 6.2 Flush history writes

```python
write_queue.flush()
```

Ensures all pending history logs are written to SQLite before cleanup.

### 6.3 Cleanup index

```python
cleanup_index(
    db_path=index_db_path,
    failed_count=failed_count,
    exception_info=exc_info,
    interrupted=interrupted,
)
```

| Condition | Action |
|-----------|--------|
| All succeeded, no exception, no interrupt | Delete `tmp/index.db` |
| Any failed | Preserve `tmp/index.db` |
| Exception occurred | Preserve `tmp/index.db` |
| Interrupted (Ctrl+C/SIGTERM) | Preserve `tmp/index.db` |

### 6.4 Restore signal handlers

```python
signal.signal(signal.SIGINT, old_sigint)
signal.signal(signal.SIGTERM, old_sigterm)
```

## Alternative flows

### Index-only mode (`--build-index`)

1. Parse args, validate
2. Load config
3. Resolve preset
4. Resolve backend
5. Scan files
6. Probe files (same as above)
7. Write all rows to user-specified DB
8. Print summary
9. Exit

### Index-run mode (`--index`)

1. Parse args, validate
2. Load config
3. Resolve preset
4. Resolve backend
5. Open existing index DB
6. Build jobs from index rows
7. Check lossy gate
8. Execute jobs
9. Cleanup

## Signal handling

The wrapper handles SIGINT and SIGTERM to ensure proper cleanup:

```python
def _signal_handler(signum, frame):
    global _run_interrupted
    _run_interrupted = True
    print("\n[yellow]Interrupted.[/yellow]", file=sys.stderr)
```

Behaviour on signal:

1. Sets `_run_interrupted` flag
2. Prints interrupt message
3. Completes current job (if in progress)
4. Exits via `finally` block with cleanup

## Error handling

### Fail-fast errors

These abort immediately before any file operations:

- Missing configuration files
- Invalid preset name
- Backend environment validation failure
- Preset/backend incompatibility

### Runtime errors

These are caught and logged:

- Conversion failures — job marked as FAILED, continue with next
- Probe failures — treated as lossless, continue with conversion
- Sidecar copy failures — logged but don't fail the job
- SQLite errors — database operations have locks and retries

### Exception safety

The `finally` block ensures:

1. Signal handlers are restored
2. Index database is cleaned up properly
3. History is committed for completed jobs

## Parallelism model

### Single-worker mode

```python
if workers == 1:
    for future in as_completed(futures):
        _drain_events_into_ui(events, progress, job_tasks)
        # Process results inline
```

### Multi-worker mode

```python
else:
    while remaining:
        _drain_events_into_ui(events, progress, job_tasks)
        for future in list(_as_completed(remaining)):
            # Process completed futures
```

Event queue:

- Workers push: `STARTED`, `FINISHED`, `LOG`, `ACTIVITY`
- Background drain thread polls at 20ms intervals for real-time UI updates
- Main thread drains between future completions
- Events processed safely on main thread only

### Async history writes

Workers push log entries to a `DBWriteQueue`:

- Single background writer thread drains the queue
- Eliminates concurrent SQLite write contention
- Supports both `threading.Queue` and `multiprocessing.Manager().Queue()`
- Caller must `flush()` to ensure all writes complete

## Example run

```sh
$ python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action leave
```

Output:

```
Scanning 156 file(s)...        ████████████████████  100%  ETA 0:00  2.4 GiB
Probing 156 file(s)...         ████████████████████  100%  ETA 0:00  156 files
Converting 156 files...
[PhaseName 45/156 files]  ████████░░░░░░░░  83%  ETA 0:32  1.2 GiB
  converting
[dim]Probing done. 3 lossy file(s) found.[/dim]

Done.  Success: 153  Skipped: 3  Failed: 0
```

## Resume behaviour

### First run

```
Source: ~/Music/album/track.flac
Output: ~/Converted/album/track.flac
Result: SUCCESS
```

### Second run (no changes)

```
Source: ~/Music/album/track.flac
Output: ~/Converted/album/track.flac
Result: SKIPPED (already converted)
```

### Second run (with `--force`)

```
Source: ~/Music/album/track.flac
Output: ~/Converted/album/track.flac
Result: SUCCESS (reconverted)
```

### Second run (output deleted)

```
Source: ~/Music/album/track.flac
Output: ~/Converted/album/track.flac
Result: SUCCESS (was missing, reconverting)
```
