---
title: Presets Reference
summary: Preset schema, per-backend encoder args, and how to write your own.
audience: [user]
weight: 30
---

This document provides a complete reference for all preset definitions in `presets.yaml`.

## Overview

Presets define how audio files should be encoded, including:

- Output file extension
- Per-backend encoder settings
- Sidecar file handling (lyrics, covers)

Presets are loaded from `presets.yaml` by `src/config/preset_loader.py`.

## Available presets

| Preset | Output | Backends | Description |
|--------|--------|----------|-------------|
| `flac-lossless` | FLAC | all | FLAC compression level 5 |
| `mp3-v0-vbr` | MP3 | all | MP3 V0 VBR (~245 kbps) |
| `mp3-320-cbr` | MP3 | all | MP3 320 kbps CBR |
| `aac-vbr-high` | M4A | all | AAC VBR quality 5 (high) |
| `qaac-cvbr-256` | M4A | dBpoweramp only | Apple AAC via QAAC 256 kbps |
| `opus-128` | OPUS | all | Opus 128 kbps |

## Preset schema

Each preset has the following structure:

```yaml
preset-name:
  ext: ".output_extension"
  backends:
    wine_dbpoweramp:
      encoder: "Encoder Name"
      args: ["arg1", "arg2"]
    native_ffmpeg:
      tool: "ffmpeg"
      args: ["-c:a", "libmp3lame", "-q:a", "0"]
      requires_encoder: "libmp3lame"
    native_dbpoweramp:
      encoder: "Encoder Name"
      args: ["arg1", "arg2"]
  sidecars:
    lyrics:
      copy: true
      extensions: [".lrc", ".txt"]
      hide: false
    covers:
      copy: true
      patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
      hide: true
```

## FLAC lossless (`flac-lossless`)

Lossless FLAC encoding at compression level 5.

- Extension: `.flac`
- Type: Lossless

### `native_ffmpeg`

```yaml
tool: "ffmpeg"
args: ["-c:a", "flac", "-compression_level", "5"]
```

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "FLAC"
args: ["-compression-level-5", "-verify"]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

## MP3 V0 VBR (`mp3-v0-vbr`)

LAME MP3 encoding at V0 variable bitrate (~245 kbps average).

- Extension: `.mp3`
- Type: Lossy

### `native_ffmpeg`

```yaml
tool: "ffmpeg"
args: ["-c:a", "libmp3lame", "-q:a", "0"]
```

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "mp3 (LAME)"
args: ["-V 0", "-encoding=\"SLOW\""]
```

## MP3 320 CBR (`mp3-320-cbr`)

LAME MP3 encoding at constant 320 kbps.

- Extension: `.mp3`
- Type: Lossy

### `native_ffmpeg`

```yaml
tool: "ffmpeg"
args: ["-c:a", "libmp3lame", "-b:a", "320k"]
```

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "mp3 (LAME)"
args: ["-b 320"]
```

## AAC VBR High (`aac-vbr-high`)

FDK-AAC encoder at VBR quality 5 (high quality).

- Extension: `.m4a`
- Type: Lossy

### `native_ffmpeg`

```yaml
tool: "ffmpeg"
args: ["-c:a", "libfdk_aac", "-vbr", "5"]
requires_encoder: "libfdk_aac"
```

{{< callout type="warning" title="FDK AAC availability" >}}The `requires_encoder` field tells the backend to check `ffmpeg -encoders` before running. If FDK AAC is not available, a clear error message is shown with installation instructions.{{< /callout >}}

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "m4a FDK (AAC)"
args: ["-m 5"]
```

## QAAC CVBR 256 (`qaac-cvbr-256`)

Apple's QAAC encoder at 256 kbps constrained VBR. Uses `CoreAudioToolbox.dll`.

- Extension: `.m4a`
- Type: Lossy

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "m4a QAAC (iTunes)"
args: ["-cbr_vbr=\"cVBR\"", "-bitrate=\"256\"", "-codec=\"LC AAC\"", "-keepsr"]
```

### Limitations

- **Does NOT support `native_ffmpeg`** — QAAC is Apple-only technology
- **Requires `CoreAudioToolbox.dll`** from iTunes installation
  - On Linux: install in the Wine prefix alongside dBpoweramp
  - On Windows: install alongside dBpoweramp or install iTunes

## Opus 128 (`opus-128`)

Opus encoding at 128 kbps.

- Extension: `.opus`
- Type: Lossy

### `native_ffmpeg`

```yaml
tool: "ffmpeg"
args: ["-c:a", "libopus", "-b:a", "128k"]
```

### `wine_dbpoweramp` / `native_dbpoweramp`

```yaml
encoder: "Opus"
args: ["-bitrate 128"]
```

## Sidecar configuration

```yaml
lyrics:
  copy: true
  extensions: [".lrc", ".txt"]
  hide: false

covers:
  copy: true
  patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
  hide: true
```

### Hide behaviour

When `hide: true`, files are renamed with a dot prefix:

| Original | Hidden |
|----------|--------|
| `cover.jpg` | `.cover.jpg` |
| `folder.png` | `.folder.png` |
| `albumart.jpg` | `.albumart.jpg` |

Files already prefixed with a dot are not modified.

This keeps your music directories clean by hiding artwork in standard file browsers.

## Creating custom presets

### Minimal preset

```yaml
presets:
  my-flac:
    ext: ".flac"
    backends:
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "flac", "-compression_level", "8"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg"], hide: true }
```

### Custom MP3 VBR quality

```yaml
presets:
  mp3-192-vbr:
    ext: ".mp3"
    backends:
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libmp3lame", "-q:a", "2"]   # ~190 kbps VBR
      wine_dbpoweramp:
        encoder: "mp3 (LAME)"
        args: ["-V 2"]
      native_dbpoweramp:
        encoder: "mp3 (LAME)"
        args: ["-V 2"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }
```

## Validation

The preset loader (`src/config/preset_loader.py`) validates presets:

| Check | Behaviour on failure |
|-------|----------------------|
| Missing `ext` | Raises `ConfigError` |
| `ext` doesn't start with `.` | Raises `ConfigError` |
| Missing `backends` | Raises `ConfigError` |
| Empty `backends` | Raises `ConfigError` |
| Invalid `extensions` type | Raises `ConfigError` |
| Invalid `hide` type | Raises `ConfigError` |
| YAML parse error | Raises `ConfigError` |

## Encoder availability

### FFmpeg encoders

FFmpeg may not include all encoders depending on build:

| Encoder | Common build | Installation |
|---------|-------------|--------------|
| `libmp3lame` | Standard | Usually included |
| `libfdk_aac` | Often excluded | `ffmpeg-full` from AUR or rebuild |
| `libopus` | Standard | Usually included |
| `flac` | Standard | Usually included |

Check available encoders:

```sh
ffmpeg -encoders 2>/dev/null | grep -E "aac|mp3|opus|flac"
```

### LAME VBR quality scale

| Quality | Bitrate (approx) |
|---------|------------------|
| `-V 0` | ~245 kbps |
| `-V 1` | ~225 kbps |
| `-V 2` | ~190 kbps |
| `-V 3` | ~175 kbps |
| `-V 4` | ~165 kbps |
| `-V 5` | ~130 kbps |
| `-V 6` | ~115 kbps |
| `-V 7` | ~100 kbps |
| `-V 8` | ~85 kbps  |
| `-V 9` | ~65 kbps  |

### FDK AAC VBR modes

| Mode | Description |
|------|-------------|
| `-m 1` | Very low (~64 kbps) |
| `-m 2` | Low (~96 kbps) |
| `-m 3` | Medium (~128 kbps) |
| `-m 4` | High (~192 kbps) |
| `-m 5` | Very high (~256 kbps) |
