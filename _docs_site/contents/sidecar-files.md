---
permalink: /sidecar-files/
layout: default
title: Sidecar Files
slug: sidecar-files
category: engineering
order: 30
summary: How lyrics and cover art are copied alongside output files.
audience: [user]
---

This document explains how the wrapper handles sidecar files like lyrics and cover art.

## Overview

Sidecar files are auxiliary files that accompany audio files, such as:

- **Lyrics** — `.lrc`, `.txt` files with synchronized or plain lyrics
- **Cover art** — `cover.jpg`, `folder.png` etc. with album artwork

The wrapper can automatically copy these files alongside converted audio files.

## Lyrics files

### Supported extensions

By default, lyrics files are identified by these extensions:

```yaml
lyrics:
  extensions: [".lrc", ".txt"]
```

### Detection

The wrapper looks for lyrics files with the same stem as the audio file:

```text
input/
├── song.flac
├── song.lrc      ← Lyrics file
└── song.txt      ← Alternative lyrics file
```

### Copy behaviour

When copying, the lyrics file maintains its extension:

```text
output/
├── song.mp3
├── song.lrc      ← Copied from input/
└── song.txt      ← Copied from input/
```

### Configuration

```yaml
lyrics:
  copy: true
  extensions: [".lrc", ".txt"]
  hide: false
```

## Cover art files

### Supported patterns

By default, cover art files are identified by these patterns:

```yaml
covers:
  patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
```

### Detection

The wrapper looks for cover files in the same directory as the audio file:

```text
input/
├── song.flac
├── cover.jpg      ← Cover file
├── cover.png      ← Alternative cover
├── folder.jpg     ← Alternative naming
└── albumart.jpg   ← Alternative naming
```

### Copy behaviour

When copying with `hide: true` (default), the filename is prefixed with a dot to hide it:

```text
output/
├── song.mp3
├── .cover.jpg     ← Copied from input/cover.jpg (hidden)
└── .cover.png     ← Copied from input/cover.png (hidden)
```

With `hide: false`, files keep their original names.

### Configuration

```yaml
covers:
  copy: true
  patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
  hide: true
```

## Hiding behaviour

The `hide` option prefixes filenames with a dot:

| Original | Hidden |
|----------|--------|
| `cover.jpg` | `.cover.jpg` |
| `folder.png` | `.folder.png` |
| `albumart.jpg` | `.albumart.jpg` |

Files already prefixed with a dot are not modified.

This keeps your music directories clean by hiding artwork in standard file browsers.

## Per-preset configuration

Each preset can define its own sidecar handling:

```yaml
flac-lossless:
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

```yaml
mp3-v0-vbr:
  sidecars:
    lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
    covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }
```

## Disabling sidecar copying

To disable sidecar copying entirely:

```yaml
flac-lossless:
  ext: ".flac"
  backends:
    native_ffmpeg:
      # ...
  sidecars:
    lyrics:
      copy: false
    covers:
      copy: false
```

## Implementation

```python
def copy_lyrics(
    infile: Path,
    outfile: Path,
    policy: SidecarPolicy | None,
) -> list[Path]:
    """Copy lyric/text files next to output."""
    if policy is None or not policy.copy:
        return []

    written: list[Path] = []
    for ext in policy.extensions:
        lyric_src = infile.with_suffix(ext)
        if lyric_src.exists():
            lyric_dst = outfile.with_suffix(ext)
            if not lyric_dst.exists():
                shutil.copy2(lyric_src, lyric_dst)
                written.append(lyric_dst)
    return written


def copy_covers(
    infile: Path,
    outfile: Path,
    policy: CoverPolicy | None,
) -> list[Path]:
    """Copy cover art files to output directory."""
    if policy is None or not policy.copy:
        return []

    written: list[Path] = []
    for pattern in policy.patterns:
        cover_src = infile.parent / pattern
        if cover_src.exists():
            dest_name = hide_filename(pattern) if policy.hide else pattern
            cover_dst = outfile.parent / dest_name
            if not cover_dst.exists():
                shutil.copy2(cover_src, cover_dst)
                written.append(cover_dst)
    return written
```

## Idempotency

Sidecar copying is idempotent:

- If the destination already exists, the file is not copied
- This prevents overwriting user modifications

## Preserving metadata

While the wrapper copies sidecar files, it does **not** embed metadata (tags) into the output files. This is handled by the encoding backend:

- **FFmpeg** can copy or strip metadata via command-line flags
- **dBpoweramp** can copy or strip metadata via its settings

If you need to embed cover art into the output file's metadata, configure the backend accordingly.

## Sidecar index storage

Sidecar files are tracked in the temporary index:

```sql
SELECT source_path, sidecar_files FROM index_entries;
```

The `sidecar_files` column contains newline-separated basename of discovered sidecar files.

## Examples

### Copy all sidecars

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy
```

### Show what sidecars would be copied (dry run)

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run
```

### Custom cover patterns

```yaml
presets:
  my-preset:
    ext: ".flac"
    backends:
      native_ffmpeg:
        # ...
    sidecars:
      lyrics:
        copy: true
        extensions: [".lrc", ".txt", ".ass"]
        hide: false
      covers:
        copy: true
        patterns: ["cover.jpg", "cover.png", "front.jpg", "back.jpg"]
        hide: true
```
