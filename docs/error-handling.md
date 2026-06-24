# Error Handling

This document describes how the wrapper handles errors at each stage of the conversion process.

---

## Overview

The wrapper implements a multi-level error handling strategy:

1. **Fail-fast validation** - Check prerequisites before starting
2. **Runtime error catching** - Handle errors gracefully during execution
3. **Exception safety** - Ensure cleanup happens regardless of errors

---

## Error Categories

### Configuration Errors

These occur before any file operations begin.

#### Missing Configuration Files

```python
try:
    settings = load_settings(Path("settings.yaml"))
except ConfigError as e:
    print(f"Config error: {e}")
    sys.exit(1)
```

#### Invalid Preset

```python
try:
    preset = get_preset(presets, args.preset)
except PresetNotFoundError as e:
    print(f"error: {e}")
    sys.exit(1)
```

### Backend Errors

These occur during backend validation.

#### FFmpeg Not Found

```
BackendError: ffmpeg binary 'ffmpeg' not found on PATH and is not an absolute path to an existing file.
Install ffmpeg with: sudo pacman -S ffmpeg  (Arch/CachyOS)
or: sudo apt install ffmpeg          (Debian/Ubuntu)
or: sudo dnf install ffmpeg          (Fedora)
```

#### Wine Prefix Missing

```
BackendError: WINEPREFIX '~/.wine-dbpoweramp' does not exist.
Create it by running: WINEPREFIX=~/.wine-dbpoweramp wineboot
Then install dBpoweramp into that prefix using a Windows installer under Wine.
```

#### CoreConverter Not Found (Windows)

```
BackendError: CoreConverter not found at 'C:\Program Files\dBpoweramp\CoreConverter.exe'.
Install dBpoweramp or update the coreconverter_path in settings.yaml:
  backend:
    native_dbpoweramp:
      coreconverter_path: 'C:\Program Files\dBpoweramp\CoreConverter.exe'
```

#### Missing Encoder

```
Encoder 'libfdk_aac' is not available in this ffmpeg build.
The ffmpeg binary being used does not include this encoder.
On CachyOS/Arch, install a full-featured ffmpeg build:
  sudo pacman -S ffmpeg-full    # from AUR, includes libfdk_aac and others
Or rebuild your ffmpeg preset without this encoder (remove it from your
presets.yaml aac-vbr-high entry's requires_encoder field).
```

### Path Configuration Errors

#### Source Path Not Ancestor

```python
# --source-path must be ancestor of --input
error: --source-path /home/user/Music is not an ancestor of --input /home/user/Downloads
```

### CLI Validation Errors

#### Mutually Exclusive Flags

```python
# --lossy-action and --no-lossy-check
error: --lossy-action and --no-lossy-check are mutually exclusive

# --dry-run with --lossy-action
error: --dry-run is an inspection-only mode and does not use --lossy-action
```

### Runtime Errors

#### Conversion Failures

Individual conversion failures are caught and logged:

```
Done.  Success: 152  Skipped: 3  Failed: 1
```

The error message is stored in the history database for later inspection.

#### Probe Errors

Probe failures (mutagen cannot read a file) are handled gracefully:

```python
try:
    _, is_lossy = future.result()
except Exception:
    # ProbeError — treat as lossless so the conversion backend
    # surfaces the real error rather than skipping the file.
    is_lossy_val = None
```

#### Sidecar Copy Errors

Sidecar copy errors are logged but don't fail the job:

```python
try:
    copy_lyrics(infile, outfile, policy)
    copy_covers(infile, outfile, policy)
except Exception as e:
    print(f"[runner] sidecar copy failed: {e}")
```

### SQLite Errors

The history database uses WAL mode with a busy timeout:

```python
self._conn.execute("PRAGMA journal_mode=WAL")
self._conn.execute("PRAGMA busy_timeout=5000")
```

This handles concurrent access gracefully without immediate failures.

---

## Signal Handling

### Interrupt Signals

The wrapper handles SIGINT (Ctrl+C) and SIGTERM:

```python
def _signal_handler(signum, frame):
    global _run_interrupted
    _run_interrupted = True
    print("\n[yellow]Interrupted.[/yellow]", file=sys.stderr)
```

**Behavior:**
1. Sets the interrupt flag
2. Prints interrupt message
3. Completes current job (if in progress)
4. Cleans up via `finally` block

### Cleanup on Interrupt

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

---

## Exception Classes

### ConfigError

```python
class ConfigError(Exception):
    """Raised when a configuration file is missing, malformed, or fails validation."""
```

### PresetNotFoundError

```python
class PresetNotFoundError(Exception):
    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
```

### BackendError

```python
class BackendError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
```

### ProbeError

```python
class ProbeError(Exception):
    def __init__(self, file: str, stderr: str) -> None:
        self.file = file
        self.stderr = stderr
```

### PathConfigError

```python
class PathConfigError(Exception):
    """Raised when a path configuration is invalid."""
```

### IndexError

```python
class IndexError(Exception):
    """Raised when the temporary index database cannot be created, opened, or written."""
```

---

## Output Verification

After every conversion, the output file is verified:

```python
def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    if not job.outfile.exists():
        return False, f"Output file not found: {job.outfile}"
    
    size = job.outfile.stat().st_size
    if size == 0:
        return False, f"Output file is empty: {job.outfile}"
    
    return True, None
```

**Why?** Some tools may exit 0 even when the output is invalid. Verification ensures we don't mark corrupt outputs as successful.

---

## Retry Behavior

The wrapper does **not** automatically retry failed conversions. Design decisions:

1. **Failure is likely persistent** - Permissions, disk full, corrupt source
2. **Retrying wastes time** - Large library conversions could take hours
3. **Manual intervention** - User should investigate and fix root cause

If you need retry logic, wrap the wrapper in a script:

```bash
#!/bin/bash
for i in 1 2 3; do
    python main.py -I ~/Music -O ~/Converted -p flac-lossless && break
    echo "Retrying after 10 seconds..."
    sleep 10
done
```

---

## Logging Errors to History

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

**Inspecting failures:**

```sh
sqlite3 conversion_history.db "SELECT * FROM history WHERE status = 'FAILED';"
```

---

## Best Practices

### Pre-flight Checks

Run these before a large batch:

```sh
# Test with single file
python main.py -I ~/Music/Artist/Album/track.flac -O ~/Test -p flac-lossless

# List lossy files
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy

# Dry run
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run
```

### Monitoring Large Runs

```sh
# Run with verbose output
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v 2>&1 | tee conversion.log
```

### Handling Failures

1. Check the history database for error messages
2. Verify source file integrity
3. Check disk space
4. Verify output directory permissions
5. Re-run with `--force` after fixing issues

---

## Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | All jobs succeeded |
| 1 | Error during setup (config, backend validation, CLI) |
| 1 | Lossy files detected without `--lossy-action` |
| 1 | Job failed (partial success possible) |

Note: The wrapper may exit 0 even if some jobs failed. Check the summary output.

---

## Debugging Tips

### Enable Debug Logging

```yaml
# settings.yaml
logging:
  level: "DEBUG"
```

### Preserve Index for Debugging

```python
# If run fails, index is preserved automatically
# To force preservation even on success:
# (not directly supported, but tmp/index.db persists)
```

### Inspect Backend Commands

```sh
# Run with verbose output
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v
```

### Test Backend in Isolation

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
