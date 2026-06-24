# Presets Reference

This document provides a complete reference for all preset definitions in `presets.yaml`.

---

## Overview

Presets define how audio files should be encoded, including:

- Output file extension
- Per-backend encoder settings
- Sidecar file handling (lyrics, covers)

Presets are loaded from `presets.yaml` by `src/config/preset_loader.py`.

---

## Available Presets

| Preset | Output | Backends | Description |
|--------|--------|----------|-------------|
| `flac-lossless` | FLAC | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp | FLAC compression level 5 |
| `mp3-v0-vbr` | MP3 | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp | MP3 V0 VBR (~245 kbps) |
| `mp3-320-cbr` | MP3 | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp | MP3 320 kbps CBR |
| `aac-vbr-high` | M4A | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp | AAC VBR quality 5 (high) |
| `qaac-cvbr-256` | M4A | wine_dbpoweramp, native_dbpoweramp | Apple AAC via QAAC 256 kbps |
| `opus-128` | OPUS | native_ffmpeg, native_dbpoweramp, wine_dbpoweramp | Opus 128 kbps |

---

## Preset Schema

Each preset has the following structure:

```yaml
preset-name:
  ext: ".output_extension"          # Output file extension
  backends:
    wine_dbpoweramp:
      encoder: "Encoder Name"       # dBpoweramp encoder identifier
      args: ["arg1", "arg2"]       # Encoder arguments
    native_ffmpeg:
      tool: "ffmpeg"               # Tool: ffmpeg, flac, lame, opusenc
      args: ["-c:a", "libmp3lame", "-q:a", "0"]
      requires_encoder: "libmp3lame"  # Optional: encoder check
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

---

## FLAC Lossless (`flac-lossless`)

Lossless FLAC encoding at compression level 5 (good balance of size/speed).

### Output
- **Extension:** `.flac`
- **Type:** Lossless

### Backend Configurations

#### native_ffmpeg

```yaml
tool: "ffmpeg"
args: ["-c:a", "flac", "-compression_level", "5"]
```

#### wine_dbpoweramp

```yaml
encoder: "FLAC"
args: ["-compression-level-5", "-verify"]
```

#### native_dbpoweramp

```yaml
encoder: "FLAC"
args: ["-compression-level-5", "-verify"]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## MP3 V0 VBR (`mp3-v0-vbr`)

LAME MP3 encoding at V0 variable bitrate (~245 kbps average).

### Output
- **Extension:** `.mp3`
- **Type:** Lossy

### Backend Configurations

#### native_ffmpeg

```yaml
tool: "ffmpeg"
args: ["-c:a", "libmp3lame", "-q:a", "0"]
```

#### wine_dbpoweramp

```yaml
encoder: "mp3 (LAME)"
args: ["-V 0", "-encoding=\"SLOW\""]
```

#### native_dbpoweramp

```yaml
encoder: "mp3 (LAME)"
args: ["-V 0", "-encoding=\"SLOW\""]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## MP3 320 CBR (`mp3-320-cbr`)

LAME MP3 encoding at constant 320 kbps.

### Output
- **Extension:** `.mp3`
- **Type:** Lossy

### Backend Configurations

#### native_ffmpeg

```yaml
tool: "ffmpeg"
args: ["-c:a", "libmp3lame", "-b:a", "320k"]
```

#### wine_dbpoweramp

```yaml
encoder: "mp3 (LAME)"
args: ["-b 320"]
```

#### native_dbpoweramp

```yaml
encoder: "mp3 (LAME)"
args: ["-b 320"]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## AAC VBR High (`aac-vbr-high`)

FDK-AAC encoder at VBR quality 5 (high quality).

### Output
- **Extension:** `.m4a`
- **Type:** Lossy

### Backend Configurations

#### native_ffmpeg

```yaml
tool: "ffmpeg"
args: ["-c:a", "libfdk_aac", "-vbr", "5"]
requires_encoder: "libfdk_aac"
```

**Note:** The `requires_encoder` field tells the backend to check `ffmpeg -encoders` before running. If FDK AAC is not available, a clear error message is shown with installation instructions.

#### wine_dbpoweramp

```yaml
encoder: "m4a FDK (AAC)"
args: ["-m 5"]
```

#### native_dbpoweramp

```yaml
encoder: "m4a FDK (AAC)"
args: ["-m 5"]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## QAAC CVBR 256 (`qaac-cvbr-256`)

Apple's QAAC encoder at 256 kbps constrained VBR. Uses Apple's CoreAudioToolbox.dll.

### Output
- **Extension:** `.m4a`
- **Type:** Lossy

### Backend Configurations

#### wine_dbpoweramp

```yaml
encoder: "m4a QAAC (iTunes)"
args: ["-cbr_vbr=\"cVBR\"", "-bitrate=\"256\"", "-codec=\"LC AAC\"", "-keepsr"]
```

#### native_dbpoweramp

```yaml
encoder: "m4a QAAC (iTunes)"
args: ["-cbr_vbr=\"cVBR\"", "-bitrate=\"256\"", "-codec=\"LC AAC\"", "-keepsr"]
```

### Limitations

- **Does NOT support `native_ffmpeg`** - QAAC is Apple-only technology
- **Requires `CoreAudioToolbox.dll`** from iTunes installation
  - On Linux: Install in the Wine prefix alongside dBpoweramp
  - On Windows: Install alongside dBpoweramp or install iTunes

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## Opus 128 (`opus-128`)

Opus encoding at 128 kbps.

### Output
- **Extension:** `.opus`
- **Type:** Lossy

### Backend Configurations

#### native_ffmpeg

```yaml
tool: "ffmpeg"
args: ["-c:a", "libopus", "-b:a", "128k"]
```

#### wine_dbpoweramp

```yaml
encoder: "Opus"
args: ["-bitrate 128"]
```

#### native_dbpoweramp

```yaml
encoder: "Opus"
args: ["-bitrate 128"]
```

### Sidecars

- **Lyrics:** Copy as `.lrc`, `.txt`
- **Covers:** Copy as `.cover.jpg`, `.cover.png`, `.folder.jpg`, `.albumart.jpg` (hidden)

---

## Sidecar Configuration

### Lyrics Sidecar

```yaml
lyrics:
  copy: true                    # Whether to copy lyrics files
  extensions: [".lrc", ".txt"] # Extensions to look for
  hide: false                   # Whether to hide (prefix with dot)
```

### Cover Sidecar

```yaml
covers:
  copy: true                                              # Whether to copy cover files
  patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
  hide: true                   # Whether to hide (prefix with dot)
```

### Hide Behavior

When `hide: true`, files are renamed with a dot prefix:
- `cover.jpg` → `.cover.jpg`
- `folder.png` → `.folder.png`

This keeps the output directory clean by hiding cover art in standard file browsers.

---

## Creating Custom Presets

### Minimal Preset Example

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

### Custom Bitrate Example

```yaml
presets:
  mp3-192-vbr:
    ext: ".mp3"
    backends:
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libmp3lame", "-q:a", "2"]  # ~190 kbps VBR
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

### Opus Custom Quality

```yaml
presets:
  opus-high:
    ext: ".opus"
    backends:
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libopus", "-b:a", "256k", "-vbr", "on"]
      wine_dbpoweramp:
        encoder: "Opus"
        args: ["-bitrate 256"]
      native_dbpoweramp:
        encoder: "Opus"
        args: ["-bitrate 256"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }
```

---

## Validation

The preset loader (`src/config/preset_loader.py`) validates presets:

| Check | Behavior on Failure |
|-------|---------------------|
| Missing `ext` | Raises `ConfigError` |
| `ext` doesn't start with `.` | Raises `ConfigError` |
| Missing `backends` | Raises `ConfigError` |
| Empty `backends` | Raises `ConfigError` |
| Invalid `extensions` type | Raises `ConfigError` |
| Invalid `hide` type | Raises `ConfigError` |
| YAML parse error | Raises `ConfigError` |

---

## Notes on Encoder Availability

### FFmpeg Encoders

FFmpeg may not include all encoders depending on build:

| Encoder | Common Build | Installation |
|---------|-------------|--------------|
| `libmp3lame` | Standard | Usually included |
| `libfdk_aac` | Often excluded | `ffmpeg-full` from AUR or rebuild |
| `libopus` | Standard | Usually included |
| `flac` | Standard | Usually included |

Check available encoders:

```sh
ffmpeg -encoders 2>/dev/null | grep -E "aac|mp3|opus|flac"
```

### dBpoweramp Encoders

Available encoders depend on your dBpoweramp installation. The wrapper passes the encoder name and arguments directly to CoreConverter.exe.

### LAME VBR Quality Scale

| Quality | Bitrate (approx) |
|---------|-----------------|
| `-V 0` | ~245 kbps |
| `-V 1` | ~225 kbps |
| `-V 2` | ~190 kbps |
| `-V 3` | ~175 kbps |
| `-V 4` | ~165 kbps |
| `-V 5` | ~130 kbps |
| `-V 6` | ~115 kbps |
| `-V 7` | ~100 kbps |
| `-V 8` | ~85 kbps |
| `-V 9` | ~65 kbps |

### FDK AAC VBR Mode

| Mode | Description |
|------|-------------|
| `-m 1` | Very low (~64 kbps) |
| `-m 2` | Low (~96 kbps) |
| `-m 3` | Medium (~128 kbps) |
| `-m 4` | High (~192 kbps) |
| `-m 5` | Very high (~256 kbps) |
