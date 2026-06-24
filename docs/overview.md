# Overview

## What is dBpoweramp Wrapper?

dBpoweramp Wrapper is a cross-platform CLI tool that provides a unified interface for audio format conversion using either:

- **Native FFmpeg** - The free, open-source encoder
- **dBpoweramp** - The commercial-grade encoder (via Wine on Linux, native on Windows)

---

## Purpose

The tool was designed to solve several common audio conversion challenges:

1. **Multi-backend support** - Use FFmpeg for free encoding or dBpoweramp for highest quality
2. **Cross-platform** - Works on Linux (with Wine) and Windows
3. **Batch processing** - Convert entire music libraries in parallel
4. **Quality preservation** - Avoid transcoding from lossy sources by default
5. **Resume support** - Pick up where you left off after interruptions

---

## Key Features

### Multi-Backend Support

| Backend | Description | Platforms |
|---------|-------------|----------|
| `native_ffmpeg` | Free FFmpeg encoder | Linux, Windows |
| `native_dbpoweramp` | Real dBpoweramp | Windows only |
| `wine_dbpoweramp` | dBpoweramp via Wine | Linux, Windows |

### Automatic Backend Detection

On Windows with dBpoweramp installed, the tool automatically uses `native_dbpoweramp` without requiring any configuration.

### Parallel Conversion

Convert multiple files simultaneously using thread or process pools:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8
```

### Lossy Source Handling

The tool detects lossy source files (MP3, AAC, etc.) and prevents accidental quality loss:

```
Lossy source files found. You must specify --lossy-action to proceed.
Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert
```

### Sidecar Preservation

Automatically copy lyrics and cover art alongside converted files:

```yaml
sidecars:
  lyrics:
    copy: true
    extensions: [".lrc", ".txt"]
  covers:
    copy: true
    patterns: ["cover.jpg", "cover.png"]
    hide: true  # Prefix with dot to hide
```

### Resume Support

Interrupted runs can be resumed from the preserved index:

```sh
python main.py --index tmp/index.db -O ~/Converted -p flac-lossless
```

---

## Architecture Overview

The tool follows a pipeline architecture:

```
CLI Args → Config Loader → Index Scanner → Job Builder → Execution Runner
                              ↓
                        Audio Inspector (lossy detection)
                              ↓
                        History DB (resume tracking)
```

### Components

| Component | Responsibility |
|-----------|----------------|
| `src/cli/` | Command-line argument parsing |
| `src/config/` | YAML configuration loading |
| `src/index/` | File discovery and indexing |
| `src/audio/` | Lossy codec detection |
| `src/jobs/` | Job list construction |
| `src/execution/` | Parallel job execution |
| `src/backends/` | FFmpeg/dBpoweramp execution |
| `src/history/` | Conversion history |
| `src/sidecars/` | Lyrics/cover copying |
| `src/ui/` | Progress display |

---

## Supported Formats

### Input Formats

| Format | Extension | Type |
|--------|-----------|------|
| FLAC | `.flac` | Lossless |
| WAV | `.wav` | Lossless |
| WAVPACK | `.wv` | Lossless |
| APE | `.ape` | Lossless |
| TTA | `.tta` | Lossless |
| MP3 | `.mp3` | Lossy |
| AAC/M4A | `.m4a`, `.mp4` | Lossy/Lossless |
| OGG | `.ogg` | Lossy |
| Opus | `.opus` | Lossy |

### Output Formats

| Format | Preset | Quality |
|--------|--------|---------|
| FLAC | `flac-lossless` | Compression level 5 |
| MP3 V0 | `mp3-v0-vbr` | ~245 kbps VBR |
| MP3 320 | `mp3-320-cbr` | 320 kbps CBR |
| AAC VBR | `aac-vbr-high` | Quality 5 (high) |
| QAAC 256 | `qaac-cvbr-256` | 256 kbps CVBR |
| Opus | `opus-128` | 128 kbps |

---

## Use Cases

### Converting a Music Library

```sh
# Convert FLAC library to MP3 V0
python main.py -I ~/Music -O ~/MP3Library -p mp3-v0-vbr --lossy-action copy
```

### Extracting from Lossless Archive

```sh
# Copy lossy files, transcode lossless
python main.py -I ~/Downloads -O ~/Library -p flac-lossless --lossy-action copy
```

### Using dBpoweramp Quality

```sh
# Use Apple's AAC encoder via dBpoweramp
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Upgrading Library Quality

```sh
# Re-encode MP3s to FLAC
python main.py -I ~/MP3Library -O ~/FLACLibrary -p flac-lossless --lossy-action convert
```

---

## Design Principles

1. **Fail-fast validation** - Check prerequisites before starting work
2. **Idempotent operations** - Safe to re-run with same arguments
3. **Graceful degradation** - Handle errors without crashing
4. **Transparent operation** - Verbose output shows exactly what's happening
5. **Zero configuration defaults** - Works out of the box with sensible defaults
