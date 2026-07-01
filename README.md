# dBpoweramp Wrapper

Convert audio files between formats — with or without dBpoweramp installed, on Linux or Windows.

`dBpoweramp Wrapper` is a CLI tool that wraps **dBpoweramp CoreConverter.exe** (via Wine on Linux, natively on Windows) and **native FFmpeg** to give you a single, portable command for batch audio conversion. It detects lossy source files, preserves lyrics and cover art, skips already-converted files, and shows a live Rich progress bar as files are processed.

---

## Quick start

```sh
# Convert FLAC library to MP3 V0 using FFmpeg (works on any platform)
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr

# Same thing via dBpoweramp on Windows (auto-detected when installed)
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256

# Dry run — see exactly what would happen before touching any files
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run

# Resume after interruption — already-converted files are skipped automatically
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

---

## Requirements

- **Python 3.10+**
- **FFmpeg** in `PATH` (for the `native_ffmpeg` backend; included in the `native_dbpoweramp`/`wine_dbpoweramp` bundles on Windows/Linux)
- **dBpoweramp Reference** (optional; auto-detected on Windows, or explicitly requested via `--backend wine_dbpoweramp` on Linux)
- **Wine** (Linux only, for the `wine_dbpoweramp` backend)

### Installation

```sh
pip install -r requirements.txt
```

`requirements.txt` declares six runtime dependencies: `pyyaml`, `rich`, `soundfile`, `miniaudio`, `numpy`, and `mutagen`.

> **QAAC note:** The `qaac-cvbr-256` preset requires Apple's `CoreAudioToolbox.dll` from an iTunes install. On Linux, install it inside the Wine prefix alongside dBpoweramp. On Windows, install it alongside dBpoweramp. If absent, QAAC fails with a clear error — not a wrapper bug.

---

## Core features

| Feature | What it means for you |
|---|---|
| **Multi-backend** | Use FFmpeg on any platform, or dBpoweramp (native on Windows, via Wine on Linux). Pick per-run with `--backend`. |
| **Auto-detection** | On Windows with dBpoweramp installed, the tool uses it automatically — no config needed. |
| **Lossy source guard** | Pre-flight probe detects MP3/AAC sources and forces you to choose `--lossy-action leave \| copy \| convert` before touching anything. |
| **Parallel conversion** | Thread or process pool (default: 4 threads, configurable with `-w`). |
| **Sidecar preservation** | Lyrics (`.lrc`, `.txt`) and cover art (`.jpg`, `.png`) are copied alongside converted files. |
| **Resume support** | Re-running skips already-comverted files. File-size tracking catches partial outputs. |
| **Output verification (post-convert)** | Every converted file is full-frame decoded via `soundfile` / `miniaudio` / `mutagen` fallback. Corrupt outputs are marked `FAILED` with the `Not - <reason>` form, not `SUCCESS`. |
| **Pre-verify skip gate (`--verify-skip`)** | Opt-in: re-decodes each skip candidate before honouring the history row. Demotes a corrupt skip to a reconvert. |
| **Database schema migration** | First run on an older `history.db` automatically creates `<db>.bak-<UTCISO>` and a `migration_audit` row. |
| **Scan cache** | Repeat runs skip the directory walk — only the lossy-probe phase runs from scratch. |

---

## Usage examples

### Simplest case

```sh
python main.py -I ~/Music/Album -O ~/Converted -p flac-lossless
```

### Preserve folder structure

```sh
python main.py -I ~/Music/Artist/Album -O ~/Converted \
    --source-path ~/Music \
    -p mp3-v0-vbr
# Output: ~/Converted/Artist/Album/*.mp3
```

### Mixed library (lossy files present)

```sh
# Copy lossy files as-is, transcode only lossless sources
python main.py -I ~/Downloads -O ~/Library \
    -p flac-lossless --lossy-action copy

# Or upgrade everything, including MP3s → FLAC
python main.py -I ~/MP3Library -O ~/FLACLibrary \
    -p flac-lossless --lossy-action convert
```

### Using a specific backend

```sh
# Force FFmpeg even on Windows
python main.py -I ~/Music -O ~/Converted -p opus-128 --backend native_ffmpeg

# Use dBpoweramp via Wine on Linux
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Advanced: build a reusable index

```sh
# Scan once, save the index to a file, run conversions from it later
python main.py -I ~/Music -O ~/Converted -p flac-lossless \
    --build-index my_index.db

# Later, use the saved index (skipping the scan/probe phases entirely)
python main.py --index my_index.db -O ~/Converted -p flac-lossless
```

### Inspect lossy files before converting

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
```

### Disable post-convert integrity verification (legacy mode)

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-output none
```

### Re-decode skip candidates before trusting them (catches pre-existing corruption)

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-skip
```

### Check history DB schema version

```sh
python main.py --db-version
```

### Inspect or migrate the history DB

```sh
python main.py db check       # print schema version, audit history, backup status
python main.py db migrate     # force-migrate to latest schema
python main.py db doctor     # check + orphaned .bak probe
```

---

## Available presets

| Preset | Output | Backends |
|--------|--------|----------|
| `flac-lossless` | FLAC, compression level 5 | FFmpeg, dBpoweramp, Wine-dBpoweramp |
| `mp3-v0-vbr` | MP3 V0 (~245 kbps VBR) | FFmpeg, dBpoweramp, Wine-dBpoweramp |
| `mp3-320-cbr` | MP3 320 kbps CBR | FFmpeg, dBpoweramp, Wine-dBpoweramp |
| `aac-vbr-high` | AAC VBR high quality | FFmpeg, dBpoweramp, Wine-dBpoweramp |
| `qaac-cvbr-256` | AAC 256 kbps via Apple QAAC | Wine-dBpoweramp, native dBpoweramp |
| `opus-128` | Opus 128 kbps | FFmpeg, dBpoweramp, Wine-dBpoweramp |

> **Backend note:** `qaac-cvbr-256` requires Apple's encoder and is not available via `native_ffmpeg`. On Linux it uses `wine_dbpoweramp`; on Windows it uses `native_dbpoweramp` if QAAC is registered with dBpoweramp.

---

## Key CLI flags

| Flag | Description |
|------|-------------|
| `-I, --input PATH` | Source file or directory |
| `-O, --output PATH` | Output root directory |
| `-p, --preset NAME` | Preset name from `presets.yaml` |
| `--source-path PATH` | Root for relative-path computation (preserves folder structure) |
| `--backend NAME` | `native_ffmpeg`, `native_dbpoweramp`, or `wine_dbpoweramp` |
| `--lossy-action` | `leave`, `copy`, or `convert` — required when lossy sources are found |
| `--no-lossy-check` | Skip the lossy detection probe entirely |
| `-w, --workers N` | Number of parallel workers (default: from `settings.yaml`) |
| `--worker-model` | `thread` or `process` (default: from `settings.yaml`) |
| `--execution-mode` | `hybrid` (interleaved) or `phased` (skip → copy → convert sequentially) |
| `--force` | Ignore resume history, reconvert everything |
| `--failed-only` | Convert only files whose latest history row is `FAILED`; everything else is skipped. Matched files are re-encoded (overwriting any existing output). Mutually exclusive with `--force`. |
| `--dry-run` | Print job list and exit |
| `--list-lossy` | Scan and print lossy files, then exit |
| `--build-index PATH` | Build index to file and exit |
| `--index PATH` | Use a pre-built index |
| `--verify-output {none,full}` | Post-convert integrity check mode (default: `full`) |
| `--verify-skip` | Pre-verify skip candidates before honouring history row |
| `--db-version` | Print DB schema version and exit (see DB inspection commands) |
| `db {check,migrate,doctor}` | Inspect or migrate the history database |
| `-v, --verbose` | Live verbose output stream |

Full reference: see [docs/cli.md](docs/cli.md)

---

## Configuration

`settings.yaml` controls backend defaults, worker counts, and history database location. See [docs/configuration.md](docs/configuration.md) for the complete reference.

---

## DB inspection commands

| Command | Description |
|---------|-------------|
| `python main.py db check [--db-path PATH]` | Print schema version, audit history, backup status; exit 0. |
| `python main.py db migrate [--db-path PATH]` | Force-migrate to latest schema (auto-runs on first conversion anyway). |
| `python main.py db doctor [--db-path PATH]` | `check` plus an orphaned-`.bak` probe. |
| `python main.py --db-version` | Print version and exit (one-liner alternative to `db check`). |

---

## Output integrity verification

Every `convert` output is integrity-checked before the job is marked SUCCESS, using a three-tier backend chain:

| Backend | Trigger | What it checks |
|---------|---------|----------------|
| `soundfile` (libsndfile) | FLAC, WAV, AIFF, CAF, and other formats supported by libsndfile | Full-frame decode; FLAC embedded MD5 verified on close; truncation guard (declared frames > 1 % above decoded frames) |
| `miniaudio` | MP3, OGG, Opus, and other formats not handled by libsndfile | Streaming decode; raises on sync/frame errors |
| `mutagen` | Last resort fallback for unsupported extensions | Tag/metadata sanity only |

Output forms rendered by the progress sink:

| `VerifyResult` status | Rendered line |
|-----------------------|---------------|
| `OK` | `Okay` |
| `NOT_OK` | `Not - <reason>` (job marked `FAILED`) |
| `UNSUPPORTED` | `Skipped - <reason>` (soft warning, job still succeeds) |

The `--verify-output {none,full}` flag controls post-convert verification. The `--verify-skip` flag adds a pre-verify gate that runs **before** `ConversionDB.should_skip()`: it re-decodes each skip-candidate's on-disk output; if it returns `NOT_OK`, the job is demoted from `SKIP` to `CONVERT` and will be re-run.

---

## Documentation

- [docs/index.md](docs/index.md) — Full documentation index
- [docs/architecture.md](docs/architecture.md) — System architecture and component overview
- [docs/configuration.md](docs/configuration.md) — `settings.yaml` reference
- [docs/cli.md](docs/cli.md) — Complete CLI reference
- [docs/presets.md](docs/presets.md) — Preset definitions
- [docs/backends.md](docs/backends.md) — Backend implementation details
