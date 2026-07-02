---
title: Error Handling
summary: Error categories, exception classes, exit codes, and verify results.
audience: [engineer]
weight: 40
---

This document describes how the wrapper handles errors at each stage of the conversion process.

## Overview

The wrapper implements a multi-level error handling strategy:

1. **Fail-fast validation** — check prerequisites before starting
2. **Runtime error catching** — handle errors gracefully during execution
3. **Exception safety** — ensure cleanup happens regardless of errors

## Error categories

### Configuration errors

These occur before any file operations begin.

#### Missing configuration files

```python
try:
    settings = load_settings(Path("settings.yaml"))
except ConfigError as e:
    print(f"Config error: {e}")
    sys.exit(1)
```

#### Invalid preset

```python
try:
    preset = get_preset(presets, args.preset)
except PresetNotFoundError as e:
    print(f"error: {e}")
    sys.exit(1)
```

### Backend errors

These occur during backend validation.

#### FFmpeg not found

```
BackendError: ffmpeg binary 'ffmpeg' not found on PATH and is not an absolute path to an existing file.
Install ffmpeg with: sudo pacman -S ffmpeg  (Arch/CachyOS)
or: sudo apt install ffmpeg          (Debian/Ubuntu)
or: sudo dnf install ffmpeg          (Fedora)
```

#### Wine prefix missing

```
BackendError: WINEPREFIX '~/.wine-dbpoweramp' does not exist.
Create it by running: WINEPREFIX=~/.wine-dbpoweramp wineboot
Then install dBpoweramp into that prefix using a Windows installer under Wine.
```

#### CoreConverter not found (Windows)

```
BackendError: CoreConverter not found at 'C:\Program Files\dBpoweramp\CoreConverter.exe'.
Install dBpoweramp or update the coreconverter_path in settings.yaml:
  backend:
    native_dbpoweramp:
      coreconverter_path: 'C:\Program Files\dBpoweramp\CoreConverter.exe'
```

#### Missing encoder

```
Encoder 'libfdk_aac' is not available in this ffmpeg build.
The ffmpeg binary being used does not include this encoder.
On CachyOS/Arch, install a full-featured ffmpeg build:
  sudo pacman -S ffmpeg-full    # from AUR, includes libfdk_aac and others
Or rebuild your ffmpeg preset without this encoder (remove it from your
presets.yaml aac-vbr-high entry's requires_encoder field).
```

### Path configuration errors

#### Source path not ancestor

```
# --source-path must be ancestor of --input
error: --source-path /home/user/Music is not an ancestor of --input /home/user/Downloads
```

### CLI validation errors

#### Mutually exclusive flags

```
# --lossy-action and --no-lossy-check
error: --lossy-action and --no-lossy-check are mutually exclusive

# --dry-run with --lossy-action
error: --dry-run is an inspection-only mode and does not use --lossy-action
```

### Runtime errors

#### Conversion failures

Individual conversion failures are caught and logged:

```
Done.  Success: 152  Skipped: 3  Failed: 1
```

The error message is stored in the history database for later inspection.

#### Probe errors

Probe failures (mutagen cannot read a file) are handled gracefully:

```python
try:
    _, is_lossy = future.result()
except Exception:
    # ProbeError — treat as lossless so the conversion backend
    # surfaces the real error rather than skipping the file.
    is_lossy_val = None
```

#### Sidecar copy errors

Sidecar copy errors are logged but don't fail the job:

```python
try:
    copy_lyrics(infile, outfile, policy)
    copy_covers(infile, outfile, policy)
except Exception as e:
    print(f"[runner] sidecar copy failed: {e}")
```

### SQLite errors

The history database uses WAL mode with a busy timeout:

```python
self._conn.execute("PRAGMA journal_mode=WAL")
self._conn.execute("PRAGMA busy_timeout=5000")
```

This handles concurrent access gracefully without immediate failures.

## Signal handling

### Interrupt signals

The wrapper handles SIGINT (Ctrl+C) and SIGTERM:

```python
def _signal_handler(signum, frame):
    global _run_interrupted
    _run_interrupted = True
    print("\n[yellow]Interrupted.[/yellow]", file=sys.stderr)
```

Behaviour:

1. Sets the interrupt flag
2. Prints interrupt message
3. Completes current job (if in progress)
4. Cleans up via `finally` block

### Cleanup on interrupt

```python
finally:
    cleanup_index(
        db_path=index_db_path,
        failed_count=failed_count,
        exception_info=exc_info,
        interrupted=_run_interrupted,
    )
```

The index is preserved for post-mortem debugging.

## Exception classes

### `ConfigError`

```python
class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or fails validation."""
```

### `PresetNotFoundError`

```python
class PresetNotFoundError(Exception):
    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
```

### `BackendError`

```python
class BackendError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
```

### `ProbeError`

```python
class ProbeError(Exception):
    def __init__(self, file: str, stderr: str) -> None:
        self.file = file
        self.stderr = stderr
```

### `PathConfigError`

```python
class PathConfigError(Exception):
    """Raised when a path configuration is invalid."""
```

### `IndexError`

```python
class IndexError(Exception):
    """Raised when the temporary index database cannot be created, opened, or written."""
```

## Output verification

After every `convert` job, `run_job` calls `_verify_output_file(job)`, which runs a full-frame decode via `src.audio.integrity.verify_file()`. The three backends are tried in priority order: `soundfile` (libsndfile) → `miniaudio` → `mutagen`. For `copy` jobs, verification falls back to existence + non-zero size. For `skip` jobs, verification is not called.

**Output forms:**

| `VerifyResult` status | Rendered line | Job outcome |
|-----------------------|---------------|-------------|
| `OK` | `Okay` | SUCCESS |
| `NOT_OK` | `Not - <reason>` | `FAILED`, `error_msg` set to the `Not - ...` line |
| `UNSUPPORTED` | `Skipped - <reason>` | SUCCESS (soft warning logged to `error_msg` as `verify skipped: ...`) |

{{< callout type="audiophile" title="Why verify?" >}}Some tools may exit 0 even when the output is corrupt or truncated. Verification ensures corrupt outputs are never marked as successful.{{< /callout >}}

## Pre-verify demotion

When `--verify-skip` is set and a skip candidate's on-disk output decodes as `NOT_OK`, the job is moved from `skipped_jobs` to `pending_jobs` and the bad `SUCCESS` row is overwritten by the next run's `log_conversion`. The `VERIFY_RESULT` event with `status=NOT_OK` is enqueued before the conversion phase starts, so the UI shows the demotion immediately.

See [Workflow]({{< relref "architecture/workflow" >}}) for the demotion policy.

## Schema migration failure

`ConversionDB.__init__` runs `migrate_to_current()` as its first action. On a migration error: the transaction is rolled back, the `.bak-<UTCISO>` file is restored, and a clear error is printed with the backup path and suggested recovery steps. The wrapper exits with code 1.

## Retry behaviour

The wrapper does **not** automatically retry failed conversions. Design decisions:

1. **Failure is likely persistent** — permissions, disk full, corrupt source
2. **Retrying wastes time** — large library conversions could take hours
3. **Manual intervention** — user should investigate and fix root cause

If you need retry logic, wrap the wrapper in a script:

```sh
#!/bin/bash
for i in 1 2 3; do
    python main.py -I ~/Music -O ~/Converted -p flac-lossless && break
    echo "Retrying after 10 seconds..."
    sleep 10
done
```

## Logging errors to history

All conversions are logged to the history database:

```python
db.log_conversion(
    source=str(job.infile),
    dest=str(job.outfile),
    job_type=job.job_type,
    command=None,
    status=result.status,
    error_msg=result.error_msg,
    stdout=result.stdout,
)
```

Inspecting failures:

```sh
sqlite3 conversion_history.db "SELECT * FROM history WHERE status = 'FAILED';"
```

## Best practices

### Pre-flight checks

Run these before a large batch:

```sh
python main.py -I ~/Music/Artist/Album/track.flac -O ~/Test -p flac-lossless
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run
```

### Monitoring large runs

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v 2>&1 | tee conversion.log
```

### Handling failures

1. Check the history database for error messages
2. Verify source file integrity
3. Check disk space
4. Verify output directory permissions
5. Re-run with `--force` after fixing issues

## Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | All jobs succeeded |
| 1 | Error during setup (config, backend validation, CLI) |
| 1 | Lossy files detected without `--lossy-action` |
| 1 | Job failed (partial success possible) |

{{< callout type="warning" title="Partial success" >}}The wrapper may exit 0 even if some jobs failed. Always check the summary output.{{< /callout >}}

## Debugging tips

### Enable debug logging

```yaml
logging:
  level: "DEBUG"
```

### Preserve index for debugging

The index is preserved automatically when a run fails or is interrupted. Inspect it directly:

```sh
sqlite3 tmp/index.db "SELECT * FROM index_entries LIMIT 10;"
```

See [File index system]({{< relref "engineering/file-index" >}}) for the full schema and query examples.

### Inspect backend commands

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v
```

### Test backend in isolation

```sh
# Test FFmpeg directly
ffmpeg -i input.flac -c:a flac -compression_level 5 output.flac

# Test Wine dBpoweramp
WINEPREFIX=~/.wine-dbpoweramp wine "C:\Program Files\dBpoweramp\CoreConverter.exe" \
    -infile="/path/to/input.wav" \
    -outfile="/path/to/output.mp3" \
    -convert_to="mp3 (LAME)" \
    -V 0
```
