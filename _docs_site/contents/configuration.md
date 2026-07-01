---
permalink: /configuration/
layout: default
title: settings.yaml Reference
slug: configuration
category: configuration
order: 10
summary: Full reference for every settings.yaml key, type, default, and override.
audience: [user, engineer]
---

This document provides a complete reference for the `settings.yaml` configuration file.

## Overview

`settings.yaml` controls the application-level behavior including:

- Default backend selection
- Backend-specific binary paths and settings
- History database location
- Worker pool configuration
- Logging level

The file is loaded and validated by `src/config/settings_loader.py` on startup.

## Full schema

```yaml
backend:
  default: "native_dbpoweramp"
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
  execution_mode: "hybrid"

logging:
  level: "INFO"
```

## Section reference

### `backend`

Top-level backend configuration.

#### `backend.default`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Default | `"native_dbpoweramp"` |
| Valid values | `"native_ffmpeg"`, `"wine_dbpoweramp"`, `"native_dbpoweramp"` |

The backend used when no `--backend` flag is passed on the command line.

```yaml
backend:
  default: "native_dbpoweramp"
```

#### `backend.auto_detect`

| Property | Value |
|----------|-------|
| Type | Boolean |
| Default | `true` |

When enabled, the wrapper automatically detects whether to use `native_dbpoweramp` on Windows:

1. If `--backend` is explicitly passed, that backend is used (auto_detect is ignored)
2. If `auto_detect` is true AND platform is Windows AND preset supports `native_dbpoweramp`, use `native_dbpoweramp`
3. Otherwise, use `backend.default`

```yaml
backend:
  auto_detect: true
```

Related flags: `--auto-detect-backend`, `--no-auto-detect-backend`.

#### `backend.native_dbpoweramp`

Configuration for the native Windows dBpoweramp backend.

##### `coreconverter_path`

| Property | Value |
|----------|-------|
| Type | String (file path) |
| Default | `"C:\\Program Files\\dBpoweramp\\CoreConverter.exe"` |

Path to the dBpoweramp CoreConverter.exe executable on Windows.

```yaml
backend:
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
```

##### `long_paths`

| Property | Value |
|----------|-------|
| Type | Boolean |
| Default | `false` |

Enable the Windows long-path workaround. When `true`, the wrapper resolves
`infile` and `outfile` to their 8.3 short names before invoking
CoreConverter on paths whose absolute form exceeds ~240 chars (the safety
threshold below Windows' MAX_PATH=260 + CreateProcessW quoting headroom).

Without this, CoreConverter cannot open the file (its `CreateFileW` calls
don't use the `\\?\` long-path prefix) and the conversion fails with
`Conversion Failed. Error writing audio data to StdIn Pipe` and a 0-byte
output file. Common on libraries with deeply nested artist/album folders
(especially JP/en libraries with kanji names).

The runtime CLI flag `--long-paths` / `--no-long-paths` overrides this
setting. On non-Windows platforms or when 8.3 names are disabled on the
volume (`fsutil 8dot3name set`), the helper degrades to a no-op and the
original long path is passed through unchanged.

```yaml
backend:
  native_dbpoweramp:
    long_paths: true
```

#### `backend.wine_dbpoweramp`

Configuration for the Wine + dBpoweramp backend.

##### `wine_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"wine"` |

The Wine binary name or absolute path. Must be discoverable via `shutil.which()` or exist as an absolute path.

```yaml
backend:
  wine_dbpoweramp:
    wine_binary: "wine"
```

##### `wine_prefix`

| Property | Value |
|----------|-------|
| Type | String (directory path) |
| Default | `"~/.wine-dbpoweramp"` |

The Wine prefix directory. This should contain the installed dBpoweramp under Wine.

```yaml
backend:
  wine_dbpoweramp:
    wine_prefix: "~/.wine-dbpoweramp"
```

##### `coreconverter_path`

| Property | Value |
|----------|-------|
| Type | String (file path) |
| Default | `"C:\\Program Files\\dBpoweramp\\CoreConverter.exe"` |

Path to CoreConverter.exe inside the Wine prefix (Windows-style path).

##### `winepath_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"winepath"` |

The winepath binary name or absolute path. Used to translate Linux paths to Windows paths.

#### `backend.native_ffmpeg`

Configuration for the native FFmpeg backend.

##### `ffmpeg_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"ffmpeg"` |

The FFmpeg binary name or absolute path.

##### `flac_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"flac"` |

The standalone FLAC binary (used if a preset prefers it over FFmpeg).

##### `lame_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"lame"` |

The standalone LAME binary (used if a preset prefers it over FFmpeg).

##### `opusenc_binary`

| Property | Value |
|----------|-------|
| Type | String |
| Default | `"opusenc"` |

The standalone opusenc binary from libopusenc (used if a preset prefers it over FFmpeg).

### `tools`

| Property | Value |
|----------|-------|
| Type | Empty mapping |
| Default | `{}` |

Reserved for future tool binary paths. Currently empty — mutagen handles audio metadata internally.

### `history`

Configuration for the conversion history database.

#### `db_path`

| Property | Value |
|----------|-------|
| Type | String (file path) |
| Default | `"conversion_history.db"` |

Path to the SQLite database file that tracks conversion history for resume support.

```yaml
history:
  db_path: "conversion_history.db"
```

Override via CLI:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --db /path/to/history.db
```

{% include components/callout.html type="audiophile" title="Schema migrations" content="The history database schema is automatically migrated on first open (see `src/history/migrations.py`). Before the first schema-changing migration, the file is backed up to `<db>.bak-<UTCISO>`. Migrations write a `migration_audit` row after each step. The `db check`, `db migrate`, `db doctor` subcommands and the `--db-version` flag all operate on this file." %}

### `execution`

Configuration for the worker pool.

#### `default_workers`

| Property | Value |
|----------|-------|
| Type | Integer |
| Default | `4` |

Default number of parallel workers for conversion. Override via `-w`/`--workers`.

#### `probe_workers`

| Property | Value |
|----------|-------|
| Type | Integer |
| Default | `16` |

Number of parallel workers for mutagen probe pre-flight (I/O-bound, can be higher than conversion workers).

#### `worker_model`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Default | `"thread"` |
| Valid values | `"thread"`, `"process"` |

| Value | Description |
|-------|-------------|
| `"thread"` | `ThreadPoolExecutor` — threads share memory, good for I/O-bound tasks |
| `"process"` | `ProcessPoolExecutor` — separate processes, better CPU isolation |

#### `execution_mode`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Default | `"hybrid"` |
| Valid values | `"hybrid"`, `"phased"` |

| Value | Description |
|-------|-------------|
| `"hybrid"` | Files processed in whatever order the pool schedules them, mixing skip/copy/convert arbitrarily (default, unchanged behaviour) |
| `"phased"` | Files run in three sequential phases in strict order: skip jobs first, then copy jobs, then convert jobs |

### `logging`

#### `level`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Default | `"INFO"` |
| Valid values | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` |

## Validation

The settings loader (`src/config/settings_loader.py`) performs validation on load:

| Check | Behaviour on failure |
|-------|----------------------|
| Missing required keys | Raises `ConfigError` |
| Wrong type for value | Raises `ConfigError` |
| Invalid enum value | Raises `ConfigError` |
| Invalid integer range | Raises `ConfigError` |
| YAML parse error | Raises `ConfigError` |

## Examples

### Minimal (Linux)

```yaml
backend:
  default: "native_dbpoweramp"
  auto_detect: false
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

history:
  db_path: "conversion_history.db"

execution:
  default_workers: 4
  probe_workers: 16
  worker_model: "thread"
  execution_mode: "hybrid"

logging:
  level: "INFO"
```

### Windows with dBpoweramp

```yaml
backend:
  default: "native_dbpoweramp"
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

history:
  db_path: "conversion_history.db"

execution:
  default_workers: 4
  probe_workers: 16
  worker_model: "thread"
  execution_mode: "hybrid"

logging:
  level: "INFO"
```

### High-performance (many cores)

```yaml
backend:
  default: "native_dbpoweramp"
  auto_detect: false
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

history:
  db_path: "conversion_history.db"

execution:
  default_workers: 8
  probe_workers: 16
  worker_model: "process"
  execution_mode: "hybrid"

logging:
  level: "WARNING"
```
