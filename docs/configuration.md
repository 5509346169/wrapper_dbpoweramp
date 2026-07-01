# Configuration Reference

This document provides a complete reference for the `settings.yaml` configuration file.

---

## Overview

`settings.yaml` controls the application-level behavior including:

- Default backend selection
- Backend-specific binary paths and settings
- History database location
- Worker pool configuration
- Logging level

The file is loaded and validated by `src/config/settings_loader.py` on startup.

---

## Full Schema

```yaml
backend:
  default: "native_dbpoweramp"   # Backend used when no --backend flag is passed
  auto_detect: true               # Auto-detect Windows vs Wine environment
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
    tmp_staging: true              # Enable Windows long-path workaround via tmp staging (see below)
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

tools: {}  # Reserved for future tool paths

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

---

## Section Reference

### `backend`

Top-level backend configuration.

#### `backend.default`

**Type:** String (enum)  
**Default:** `"native_dbpoweramp"`  
**Valid values:** `"native_ffmpeg"`, `"wine_dbpoweramp"`, `"native_dbpoweramp"`

The backend used when no `--backend` flag is passed on the command line.

```yaml
backend:
  default: "native_dbpoweramp"
```

---

#### `backend.auto_detect`

**Type:** Boolean  
**Default:** `true`

When enabled, the wrapper automatically detects whether to use `native_dbpoweramp` on Windows:

1. If `--backend` is explicitly passed, that backend is used (auto_detect is ignored)
2. If `auto_detect` is true AND platform is Windows AND preset supports `native_dbpoweramp`, use `native_dbpoweramp`
3. Otherwise, use `backend.default`

```yaml
backend:
  auto_detect: true
```

**Related flags:**
- `--auto-detect-backend` - Force enable auto-detection
- `--no-auto-detect-backend` - Force disable auto-detection

---

#### `backend.native_dbpoweramp`

Configuration for the native Windows dBpoweramp backend.

##### `backend.native_dbpoweramp.coreconverter_path`

**Type:** String (file path)  
**Default:** `"C:\\Program Files\\dBpoweramp\\CoreConverter.exe"`

Path to the dBpoweramp CoreConverter.exe executable on Windows.

```yaml
backend:
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
```

##### `backend.native_dbpoweramp.tmp_staging`

**Type:** Boolean  
**Default:** `true`

Enable the Windows long-path workaround via tmp staging. When `true`,
the wrapper copies each conversion's source to a short path under
`./tmp/audio/src/` and tells CoreConverter to write its output to a short
path under `./tmp/audio/dst/`, then `shutil.copy2()`s the converted file
from the staged output to the original long destination on success, and
unlinks both staged artefacts. This is a literal three-step copy chain
(`copy -> convert -> copy`) so neither the encoder nor the wrapper ever
sees a path that exceeds MAX_PATH, and a partially-written staged
output stays recoverable in `tmp/audio/dst/` if the destination volume
fills up mid-copy.

Without this, CoreConverter cannot open the file (its `CreateFileW`
calls don't use the `\\?\` long-path prefix) and the conversion fails
with `Conversion Failed. Error writing audio data to StdIn Pipe` and a
0-byte output file. This is a common failure on libraries with deeply
nested artist/album folders (especially JP/en libraries with kanji
names) where the absolute path easily exceeds 260 chars.

Staging is opt-in per-path: it only kicks in when the source or
destination exceeds ~240 chars, so short paths pay no I/O cost. The
per-job I/O cost is one full source copy — negligible compared to the
encoding cost (which is CPU-bound, not I/O-bound).

The runtime CLI flag `--tmp-staging` / `--no-tmp-staging` overrides this
setting. On non-Windows platforms the helper is a no-op and the original
paths are passed through unchanged.

```yaml
backend:
  native_dbpoweramp:
    tmp_staging: true
```

> See also: [CLI reference — `--failed-only`](cli.md#--failed-only) for
> retrying only the previously-failed subset of a batch without re-running
> files that already succeeded.

---

#### `backend.wine_dbpoweramp`

Configuration for the Wine + dBpoweramp backend.

##### `backend.wine_dbpoweramp.wine_binary`

**Type:** String  
**Default:** `"wine"`

The Wine binary name or absolute path. Must be discoverable via `shutil.which()` or exist as an absolute path.

```yaml
backend:
  wine_dbpoweramp:
    wine_binary: "wine"
```

**Install (Linux):**
```sh
sudo pacman -S wine    # Arch/CachyOS
sudo apt install wine  # Debian/Ubuntu
sudo dnf install wine  # Fedora
```

---

##### `backend.wine_dbpoweramp.wine_prefix`

**Type:** String (directory path)  
**Default:** `"~/.wine-dbpoweramp"`

The Wine prefix directory. This should contain the installed dBpoweramp under Wine.

```yaml
backend:
  wine_dbpoweramp:
    wine_prefix: "~/.wine-dbpoweramp"
```

**Setup:**
```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
# Then run dBpoweramp installer:
WINEPREFIX=~/.wine-dbpoweramp wine /path/to/dBpowerampReference.exe
```

---

##### `backend.wine_dbpoweramp.coreconverter_path`

**Type:** String (file path)  
**Default:** `"C:\\Program Files\\dBpoweramp\\CoreConverter.exe"`

Path to CoreConverter.exe inside the Wine prefix (Windows-style path).

```yaml
backend:
  wine_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
```

---

##### `backend.wine_dbpoweramp.winepath_binary`

**Type:** String  
**Default:** `"winepath"`

The winepath binary name or absolute path. Used to translate Linux paths to Windows paths.

```yaml
backend:
  wine_dbpoweramp:
    winepath_binary: "winepath"
```

---

#### `backend.native_ffmpeg`

Configuration for the native FFmpeg backend.

##### `backend.native_ffmpeg.ffmpeg_binary`

**Type:** String  
**Default:** `"ffmpeg"`

The FFmpeg binary name or absolute path.

```yaml
backend:
  native_ffmpeg:
    ffmpeg_binary: "ffmpeg"
```

**Install:**
```sh
sudo pacman -S ffmpeg    # Arch/CachyOS
sudo apt install ffmpeg  # Debian/Ubuntu
sudo dnf install ffmpeg  # Fedora
```

---

##### `backend.native_ffmpeg.flac_binary`

**Type:** String  
**Default:** `"flac"`

The standalone FLAC binary (used if a preset prefers it over FFmpeg).

```yaml
backend:
  native_ffmpeg:
    flac_binary: "flac"
```

---

##### `backend.native_ffmpeg.lame_binary`

**Type:** String  
**Default:** `"lame"`

The standalone LAME binary (used if a preset prefers it over FFmpeg).

```yaml
backend:
  native_ffmpeg:
    lame_binary: "lame"
```

---

##### `backend.native_ffmpeg.opusenc_binary`

**Type:** String  
**Default:** `"opusenc"`

The standalone opusenc binary from libopusenc (used if a preset prefers it over FFmpeg).

```yaml
backend:
  native_ffmpeg:
    opusenc_binary: "opusenc"
```

---

### `tools`

**Type:** Empty mapping  
**Default:** `{}`

Reserved for future tool binary paths. Currently empty as mutagen handles audio metadata internally without external binaries.

---

### `history`

Configuration for the conversion history database.

#### `history.db_path`

**Type:** String (file path)  
**Default:** `"conversion_history.db"`

Path to the SQLite database file that tracks conversion history for resume support.

```yaml
history:
  db_path: "conversion_history.db"
```

**Override via CLI:**
```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --db /path/to/history.db
```

The history database schema is automatically migrated on first open (see `src/history/migrations.py`). Before the first schema-changing migration, the file is backed up to `<db>.bak-<UTCISO>`. The migration is verbose-logged to the console: `Migrated history.db from v1 -> v2 (4 rows preserved, backup at history.db.bak-2026-06-28T14:30:00Z)` or `Schema up-to-date (v2)` if nothing changed. The `db check`, `db migrate`, `db doctor` subcommands and the `--db-version` flag all operate on the file at `history.db_path`.

---

### `execution`

Configuration for the worker pool.

#### `execution.default_workers`

**Type:** Integer  
**Default:** `4`

Default number of parallel workers for conversion.

```yaml
execution:
  default_workers: 4
```

**Override via CLI:**
```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8
```

---

#### `execution.probe_workers`

**Type:** Integer  
**Default:** `16`

Number of parallel workers for mutagen probe pre-flight (I/O bound, can be higher than conversion workers).

```yaml
execution:
  probe_workers: 16
```

---

#### `execution.worker_model`

**Type:** String (enum)  
**Default:** `"thread"`

Worker pool implementation.

| Value | Description |
|-------|-------------|
| `"thread"` | `ThreadPoolExecutor` - threads share memory, good for I/O-bound tasks |
| `"process"` | `ProcessPoolExecutor` - separate processes, better CPU isolation |

```yaml
execution:
  worker_model: "thread"
```

**Override via CLI:**
```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --worker-model process
```

---

#### `execution.execution_mode`

**Type:** String (enum)  
**Default:** `"hybrid"`

Execution mode for job scheduling.

| Value | Description |
|-------|-------------|
| `"hybrid"` | Files are processed in whatever order the pool schedules them, mixing skip/copy/convert arbitrarily (default, unchanged behaviour) |
| `"phased"` | Files run in three sequential phases in strict order: skip jobs first, then copy jobs, then convert jobs |

```yaml
execution:
  execution_mode: "phased"
```

**Override via CLI:**
```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --execution-mode phased
```

---

### `logging`

Configuration for logging output.

#### `logging.level`

**Type:** String (enum)  
**Default:** `"INFO"`  
**Valid values:** `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`

Logging verbosity level.

```yaml
logging:
  level: "INFO"
```

---

## Validation

The settings loader (`src/config/settings_loader.py`) performs validation on load:

| Check | Behavior on Failure |
|-------|---------------------|
| Missing required keys | Raises `ConfigError` |
| Wrong type for value | Raises `ConfigError` |
| Invalid enum value | Raises `ConfigError` |
| Invalid integer range | Raises `ConfigError` |
| YAML parse error | Raises `ConfigError` |

---

## Examples

### Minimal Configuration (Linux)

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

### High-Performance (Many Cores)

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
