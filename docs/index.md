# dBpoweramp Wrapper Documentation

A comprehensive CLI tool that wraps **dBpoweramp CoreConverter.exe** (via Wine) and **native FFmpeg** for cross-platform audio format conversion.

---

## Table of Contents

### Getting Started
- [Overview](overview.md) - Project purpose and key features
- [Installation](installation.md) - How to install dependencies on Linux and Windows

### Configuration
- [Configuration Reference](configuration.md) - Complete `settings.yaml` reference with all options explained
- [Presets Reference](presets.md) - All preset definitions, parameters, and backend compatibility

### Usage
- [Command-Line Interface](cli.md) - Complete CLI reference with all flags, options, and arguments
- [Workflow](workflow.md) - How a conversion run flows from start to finish

### Technical Reference
- [Architecture](architecture.md) - System architecture and component overview
- [Backends](backends.md) - How each backend (native_ffmpeg, native_dbpoweramp, wine_dbpoweramp) works
- [Module Reference](modules.md) - Each module's purpose, functions, and classes
- [Public API](api.md) - Public API reference for programmatic access

### Additional Topics
- [Lossy Source Handling](lossy-handling.md) - How the tool detects and handles lossy audio sources
- [Sidecar Files](sidecar-files.md) - How lyrics and cover art are preserved
- [File Index System](file-index.md) - The temporary SQLite index database explained
- [Error Handling](error-handling.md) - What errors can occur and how they're handled

### Testing
- [Running Tests](testing.md) - How to run the test suite

---

## Quick Start

```sh
# Convert a folder using dBpoweramp (default on Windows with auto-detection)
python main.py -I ~/Music -O ~/Converted -p flac-lossless

# Convert using FFmpeg (explicit)
python main.py -I ~/Music -O ~/Converted -p flac-lossless --backend native_ffmpeg

# Convert using dBpoweramp via Wine
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp

# Dry run - see what would be converted
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run

# Verbose output
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-backend** | FFmpeg (native), dBpoweramp (via Wine on Linux, native on Windows) |
| **Auto-detection** | Automatically uses real dBpoweramp on Windows when available |
| **Parallel conversion** | Threaded or multiprocess workers for batch operations |
| **Lossy handling** | Detect, skip, copy, or transcode lossy audio sources |
| **Sidecar preservation** | Automatically copies lyrics and cover art |
| **Resume support** | Skips already-converted files, handles interruptions gracefully |
| **SQLite reliability** | WAL mode with busy timeout for safe concurrent database access |
| **Output verification** | Validates output files before marking conversions as successful |

---

## Available Presets

| Preset | Output Format | Backends |
|--------|--------------|----------|
| `flac-lossless` | FLAC (compression level 5) | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `mp3-v0-vbr` | MP3 V0 VBR | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `mp3-320-cbr` | MP3 320 kbps CBR | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `aac-vbr-high` | AAC VBR high quality | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |
| `qaac-cvbr-256` | AAC 256 kbps via QAAC | wine_dbpoweramp, native_dbpoweramp |
| `opus-128` | Opus 128 kbps | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp |

---

## File Index

Every run builds a temporary snapshot of the discovered files in `tmp/index.db` (a SQLite database). The database is the **single source of truth** for the conversion step.

### Index Cleanup

| Outcome | `tmp/index.db` |
|---------|----------------|
| All jobs succeeded, no interrupt | **Deleted** automatically |
| Any job failed or exception | **Preserved**, with a hint printed |
| Interrupted (Ctrl+C / SIGTERM) | **Preserved**, with a hint printed |

---

## Getting Help

```sh
# Show help
python main.py --help

# List lossy files without converting
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
```

---

## License

This project is provided as-is for personal and educational use.
