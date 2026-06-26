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
  default: "native_ffmpeg"        # Backend used when no --backend flag is passed
  auto_detect: true               # Auto-detect Windows vs Wine environment
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

tools: {}  # Reserved for future tool paths

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

## Section Reference

### `backend`

Top-level backend configuration.

#### `backend.default`

**Type:** String (enum)  
**Default:** `"native_ffmpeg"`  
**Valid values:** `"native_ffmpeg"`, `"wine_dbpoweramp"`, `"native_dbpoweramp"`

The backend used when no `--backend` flag is passed on the command line.

```yaml
backend:
  default: "native_ffmpeg"
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
**Default:** `8`

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
  default: "native_ffmpeg"
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

logging:
  level: "INFO"
```

### High-Performance (Many Cores)

```yaml
backend:
  default: "native_ffmpeg"
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

logging:
  level: "WARNING"
```
