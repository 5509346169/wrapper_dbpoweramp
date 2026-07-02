---
title: Overview
summary: Project purpose, use cases, and design principles.
audience: [user, engineer]
weight: 20
---

## What is dBpoweramp Wrapper?

dBpoweramp Wrapper is a cross-platform CLI tool that provides a unified interface for audio format conversion using either:

- **Native FFmpeg** — the free, open-source encoder
- **dBpoweramp** — the commercial-grade encoder (via Wine on Linux, native on Windows)

## Purpose

The tool was designed to solve several common audio conversion challenges:

1. **Multi-backend support** — use FFmpeg for free encoding or dBpoweramp for highest quality
2. **Cross-platform** — works on Linux (with Wine) and Windows
3. **Batch processing** — convert entire music libraries in parallel
4. **Quality preservation** — avoid transcoding from lossy sources by default
5. **Resume support** — pick up where you left off after interruptions

## Key features

### Multi-backend support

| Backend | Description | Platforms |
|---------|-------------|----------|
| `native_ffmpeg` | Free FFmpeg encoder | Linux, Windows |
| `native_dbpoweramp` | Real dBpoweramp | Windows only |
| `wine_dbpoweramp` | dBpoweramp via Wine | Linux, Windows |

### Automatic backend detection

On Windows with dBpoweramp installed, the tool automatically uses `native_dbpoweramp` without any configuration.

### Parallel conversion

Convert multiple files simultaneously using thread or process pools:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8
```

### Lossy source handling

The tool detects lossy source files (MP3, AAC, etc.) and prevents accidental quality loss:

```
Lossy source files found. You must specify --lossy-action to proceed.
Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert
```

See [Lossy source handling]({{< relref "engineering/lossy-handling" >}}) for the full detection cascade.

### Sidecar preservation

Automatically copy lyrics and cover art alongside converted files:

```yaml
sidecars:
  lyrics:
    copy: true
    extensions: [".lrc", ".txt"]
  covers:
    copy: true
    patterns: ["cover.jpg", "cover.png"]
    hide: true
```

See [Sidecar files]({{< relref "engineering/sidecar-files" >}}) for the full policy reference.

### Resume support

Interrupted runs can be resumed from the preserved index:

```sh
python main.py --index tmp/index.db -O ~/Converted -p flac-lossless
```

## Architecture overview

The tool follows a pipeline architecture:

```text
CLI Args → Config Loader → Index Scanner → Job Builder → Execution Runner
                              ↓
                        Audio Inspector (lossy detection)
                              ↓
                        History DB (resume tracking)
```

For the deep dive see [Architecture]({{< relref "architecture" >}}).

## Supported formats

### Input formats

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

### Output formats

| Format | Preset | Quality |
|--------|--------|---------|
| FLAC | `flac-lossless` | Compression level 5 |
| MP3 V0 | `mp3-v0-vbr` | ~245 kbps VBR |
| MP3 320 | `mp3-320-cbr` | 320 kbps CBR |
| AAC VBR | `aac-vbr-high` | Quality 5 (high) |
| QAAC 256 | `qaac-cvbr-256` | 256 kbps CVBR |
| Opus | `opus-128` | 128 kbps |

See [Presets]({{< relref "configuration/presets" >}}) for full per-backend arguments.

## Use cases

### Converting a music library

```sh
python main.py -I ~/Music -O ~/MP3Library -p mp3-v0-vbr --lossy-action copy
```

### Extracting from a lossless archive

```sh
python main.py -I ~/Downloads -O ~/Library -p flac-lossless --lossy-action copy
```

### Using dBpoweramp quality

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Upgrading library quality

```sh
python main.py -I ~/MP3Library -O ~/FLACLibrary -p flac-lossless --lossy-action convert
```

## Design principles

1. **Fail-fast validation** — check prerequisites before starting work
2. **Idempotent operations** — safe to re-run with the same arguments
3. **Graceful degradation** — handle errors without crashing
4. **Transparent operation** — verbose output shows exactly what's happening
5. **Zero-configuration defaults** — works out of the box with sensible defaults
