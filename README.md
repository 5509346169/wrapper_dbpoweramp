# dBpoweramp Wrapper

A CLI tool that wraps **dBpoweramp CoreConverter.exe** (via Wine) and **native FFmpeg** for
cross-platform audio format conversion. On Linux, it calls the real dBpoweramp encoders through
Wine, and also provides a fully native FFmpeg path for users who want zero Wine dependency.
On Windows, it runs natively using the real dBpoweramp CoreConverter.exe.

See `docs/` for comprehensive documentation covering architecture, configuration, CLI, presets, backends, and more.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
  - [Linux](#linux)
  - [Windows](#windows)
  - [Python dependencies](#python-dependencies)
- [Quick start](#quick-start)
- [Available presets](#available-presets)
- [CLI flags](#cli-flags)
- [Lossy source files](#lossy-source-files)
- [Resume / history](#resume--history)
- [Sidecar files](#sidecar-files)
- [File index](#file-index)
- [Backend selection](#backend-selection)
- [Known limitations](#known-limitations)
- [Design docs](#design-docs)

---

## Features

- **Multi-backend support**: FFmpeg (native), dBpoweramp (via Wine on Linux, native on Windows)
- **Automatic backend detection**: On Windows, automatically uses real dBpoweramp when available
- **Parallel conversion**: Threaded or multiprocess workers for batch operations
- **Lossy source handling**: Detect, skip, copy, or transcode lossy audio sources
- **Sidecar preservation**: Automatically copies lyrics and cover art
- **Resume support**: Skips already-converted files, handles interruptions gracefully
- **SQLite reliability**: WAL mode with busy timeout and async writes for safe concurrent database access
- **Output verification**: Validates output files before marking conversions as successful
- **Scan cache**: Reuses previous scan results to skip directory walks on repeat runs

---

## Installation

### Linux

Install audio tools from the official CachyOS repos:

```sh
sudo pacman -S ffmpeg wine python-pyyaml python-rich
```

| Dependency | Purpose |
|------------|---------|
| `ffmpeg` | Provides `ffmpeg` and `ffprobe`. For `aac-vbr-high` with FDK AAC, use `ffmpeg-full` from AUR. |
| `wine` | Provides `wine`, `winepath`, and Wine runtime. No `wine-mono` or `wine-gecko` needed. |
| `python-pyyaml` | YAML configuration parsing |
| `python-rich` | Terminal UI with colored output and progress bars |

### Windows

- **Python 3.10+** recommended
- Install dBpoweramp Reference using the official Windows installer
- Default path: `C:\Program Files\dBpoweramp\CoreConverter.exe`
- Install Python dependencies:

```sh
pip install pyyaml rich
```

No Wine needed on Windows — paths are passed verbatim to `CoreConverter.exe`.

### Python dependencies

```sh
pip install -r requirements.txt
# or, with uv:
uv sync
```

`requirements.txt` and `pyproject.toml` both declare only `pyyaml` and `rich`.

### Wine prefix setup (Linux only)

If you plan to use the `wine_dbpoweramp` backend, create a dedicated Wine prefix and install
dBpoweramp inside it:

```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
```

Then run the dBpoweramp installer inside the prefix:

```sh
WINEPREFIX=~/.wine-dbpoweramp wine /path/to/dBpowerampReference.exe
```

> **Note:** The `qaac-cvbr-256` preset requires Apple's `CoreAudioToolbox.dll` from an iTunes
> install (install inside the Wine prefix on Linux; install alongside dBpoweramp on Windows).
> If absent, QAAC fails with a clear error — this is not a wrapper bug.

---

## Quick start

### Convert a folder (FFmpeg)

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

### Convert a folder (dBpoweramp via Wine)

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### More examples

```sh
# MP3 V0 via FFmpeg
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr

# Opus 128 via dBpoweramp
python main.py -I ~/Music -O ~/Converted -p opus-128 --backend wine_dbpoweramp

# AAC VBR via FFmpeg (requires libfdk_aac)
python main.py -I ~/Music -O ~/Converted -p aac-vbr-high

# Preserve folder structure with --source-path
python main.py -I ~/Music/Artist/Album -O ~/Converted \
    --source-path ~/Music \
    -p flac-lossless
# Output: ~/Converted/Artist/Album/...

# Dry run — see what would be converted
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run

# Verbose output
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v
```

---

## Available presets

| Preset | Output | Backends |
|--------|--------|----------|
| `flac-lossless` | FLAC (compression level 5) | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `mp3-v0-vbr` | MP3 V0 VBR | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `mp3-320-cbr` | MP3 320 kbps CBR | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `aac-vbr-high` | AAC VBR high quality | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `qaac-cvbr-256` | AAC 256 kbps via QAAC | wine_dbpoweramp, native_dbpoweramp |
| `opus-128` | Opus 128 kbps | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |

`native_ffmpeg` is the default backend (set in `settings.yaml`). Override with `--backend`.

---

## CLI flags

| Flag | Required | Description |
|------|----------|-------------|
| `-I, --input PATH` | yes | File or directory to convert |
| `-O, --output PATH` | yes | Output root directory |
| `-p, --preset NAME` | yes | Preset name from `presets.yaml` |
| `--source-path PATH` | no | Root for relative-path math; `--input` must be inside it |
| `--backend NAME` | no | `wine_dbpoweramp`, `native_dbpoweramp`, or `native_ffmpeg` |
| `--auto-detect-backend` | no | Force auto-detection for this run |
| `--no-auto-detect-backend` | no | Force-disable auto-detection for this run |
| `--lossy-action ACTION` | conditional | `leave`, `copy`, or `convert`. **Required if lossy files found.** |
| `--no-lossy-check` | no | Disable ffprobe lossy detection entirely |
| `-w, --workers N` | no | Thread/process pool size (default from `settings.yaml`) |
| `--worker-model MODEL` | no | `thread` or `process` (default from `settings.yaml`) |
| `-v, --verbose` | no | Live verbose conversion stream |
| `--exclude DIR` | no | Folder names to skip; can be repeated |
| `--db PATH` | no | Override history database path |
| `--force` | no | Ignore resume history, reconvert everything |
| `--dry-run` | no | Build and print job list without converting |
| `--list-lossy` | no | Scan and print lossy files, then exit |
| `--build-index PATH` | no | Build index to file and exit |
| `--index PATH` | no | Use pre-built index |

---

## Lossy source files

The lossy-action gate is a **hard error**. If any lossy source files are detected (via `ffprobe`
codec detection — not by file extension) and `--lossy-action` is not given, the run aborts
immediately before touching the output directory or history database.

### Available actions

| Action | Description |
|--------|-------------|
| `leave` | Skip lossy files; they appear as `SKIPPED` in the summary |
| `copy` | Copy lossy files as-is to the output tree (no transcoding) |
| `convert` | Transcode lossy sources to the target format |

### Related flags

- `--no-lossy-check`: Disable the probe entirely. Use when your source is all-lossless and
  you want to skip the pre-flight scan on very large libraries.
- `--list-lossy`: Scan and print lossy files found, then exit. Useful for deciding which
  policy to use before running the full batch.

---

## Resume / history

Successful conversions are logged to `conversion_history.db` (SQLite). Re-running against the
same input/output paths skips already-completed conversions. Use `--force` to reconvert
everything.

The history table tracks `job_type` (`convert` / `copy`) — a file previously copied as-is
under a `copy` policy is not skipped if you re-run with a `convert` policy.

History writes use an async queue pattern: workers push log entries to a background writer
thread, eliminating concurrent write contention. The caller must call `flush()` to ensure
all writes complete before cleanup.

### Reliability features

The wrapper includes safeguards to ensure conversions produce valid output:

- **WAL mode**: SQLite uses Write-Ahead Logging for safe concurrent access from multiple
  worker threads, with a 5-second busy timeout to handle contention gracefully.
- **Async writes**: History logging is queued and written by a dedicated thread, preventing
  concurrent write contention between workers.
- **Output verification**: After every conversion or copy, the wrapper verifies the output
  file exists and has non-zero size before marking the job as SUCCESS. If verification
  fails, the job is logged as FAILED with an error message — even if the external tool
  reported exit code 0.
- **File size tracking**: The stored output file size is compared on resume; if the size
  differs from the stored value, the file is reconverted.

---

## Sidecar files

Lyric and cover-art files are copied alongside converted audio files per the preset's
`sidecars` block in `presets.yaml`. When `hide: true` (the default for covers), the cover is
renamed to a dot-prefixed name (e.g. `cover.jpg` → `.cover.jpg`) so it is hidden in
standard file browsers.

---

## File index

Every run builds a temporary snapshot of the discovered files in `tmp/index.db` (a SQLite
database) before the lossy gate runs. The database is the **single source of truth** for the
conversion step: after the scan, rows are enriched with `dest_path`, `job_type`, and
`is_lossy`, written to SQLite, and then read back to build the `ConversionJob` list that
feeds the converter.

### Scan cache

The wrapper maintains a **scan cache** in `tmp/` that stores the results of directory
scans. On repeat runs against the same input and excludes, the cache is reused to skip
the directory walk entirely — only the probe phase (lossy detection) runs from scratch.
The cache is keyed by input path and excludes list, so different input directories or
different exclude patterns create new cache entries.

Disable with `--no-scan-cache` to force a fresh scan every run.

### Index cleanup

| Outcome | `tmp/index.db` |
|---------|----------------|
| All jobs succeeded, no interrupt | **Deleted** automatically |
| Any job failed or exception | **Preserved**, with a hint printed |
| Interrupted (Ctrl+C / SIGTERM) | **Preserved**, with a hint printed |

The cleanup decision is made in the `finally:` block of `main._main` so it runs on every
exit path.

### Inspecting a preserved index

```sh
sqlite3 tmp/index.db "SELECT source_path, dest_path, job_type, is_lossy, file_size FROM index_entries LIMIT 10;"
```

### Schema

```sql
CREATE TABLE index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path  TEXT NOT NULL,
    dest_path    TEXT NOT NULL,
    job_type     TEXT NOT NULL,
    file_size    INTEGER NOT NULL,
    sidecar_files TEXT NOT NULL,
    mtime        REAL NOT NULL,
    is_lossy     INTEGER,        -- 0/1, NULL = not probed (--no-lossy-check)
    created_at   TEXT NOT NULL
)
```

`is_lossy` is `1` for lossy sources (MP3, AAC), `0` for lossless (FLAC), and `NULL` when
`--no-lossy-check` was used.

The `tmp/` directory is gitignored. To clear a stale index manually, delete `tmp/index.db`.

---

## Backend selection

### Resolution order

For each run, the wrapper picks the backend as follows:

1. If `--backend NAME` is given on the command line, that wins outright.
2. Otherwise, if `auto_detect` is enabled and the platform is Windows, and the selected
   preset has a `native_dbpoweramp` block, use `native_dbpoweramp`.
3. Otherwise, fall back to `backend.default` from `settings.yaml`.

### Available backends

| Backend | Linux | Windows | Description |
|--------|-------|---------|-------------|
| `native_ffmpeg` | ✓ | ✓ | FFmpeg encoder, no external dependencies |
| `native_dbpoweramp` | ✗ | ✓ | Real dBpoweramp CoreConverter.exe |
| `wine_dbpoweramp` | ✓ | ✓ | dBpoweramp via Wine (Linux only) |

> **Note:** `qaac-cvbr-256` does **not** support `native_dbpoweramp` (QAAC is Apple-only).
> It uses `wine_dbpoweramp` on Linux and `native_dbpoweramp` on Windows (if QAAC is
> registered with dBpoweramp).

### Configuration

In `settings.yaml`, the `backend:` block:

```yaml
backend:
  default: "native_ffmpeg"
  auto_detect: true
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
```

---

## Known limitations

- **QAAC requires CoreAudioToolbox.dll.** The `qaac-cvbr-256` preset depends on Apple's
  DLL from an iTunes install. If absent, QAAC fails with a readable error.

- **libfdk_aac may be absent.** Repo `ffmpeg` often omits `libfdk_aac`. The wrapper checks
  `ffmpeg -encoders` before running `aac-vbr-high` and fails with an actionable message.
  Install `ffmpeg-full` from AUR or rebuild with FDK AAC enabled.

- **winepath dependency (Linux).** Path translation for `wine_dbpoweramp` requires
  `winepath`, which ships with `wine`. The wrapper validates its presence at startup.

- **Double-probing cost.** Each source file is probed once with `ffprobe` during the
  pre-flight lossy-classification scan. For large libraries this is the dominant pre-flight
  cost.

---

## Documentation

For comprehensive documentation, see the `docs/` folder:

- [docs/index.md](docs/index.md) — Documentation index with links to all topics
- [docs/architecture.md](docs/architecture.md) — System architecture and component overview
- [docs/configuration.md](docs/configuration.md) — Complete settings.yaml reference
- [docs/cli.md](docs/cli.md) — Complete CLI reference
- [docs/presets.md](docs/presets.md) — Preset definitions and parameters
- [docs/backends.md](docs/backends.md) — Backend implementation details
- [docs/modules.md](docs/modules.md) — Module reference
- [docs/workflow.md](docs/workflow.md) — How a conversion run works
