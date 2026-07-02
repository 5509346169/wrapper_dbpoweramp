---
title: Lossy Source Handling
summary: Three-tier lossy detection cascade and the four lossy actions.
audience: [user, engineer]
weight: 20
---

This document explains how the wrapper detects and handles lossy audio source files.

## Overview

Lossy audio files (MP3, AAC, Opus, etc.) are compressed with data loss. When converting to a lossless format, transcoding from a lossy source introduces additional quality loss. The wrapper provides several options to handle this scenario.

## What is "lossy"?

A file is considered "lossy" if it uses a lossy compression codec:

| Codec type | Examples |
|------------|----------|
| Lossy | MP3, AAC, Ogg Vorbis, Opus, WMA, AC3, DTS |
| Lossless | FLAC, ALAC, WAV, APE, WavPack, TTA |

## Detection cascade

The wrapper uses a three-tier detection cascade, from fastest to most accurate:

### Tier 1: extension lookup (zero I/O)

The file extension determines lossy/lossless when unambiguous.

**Unambiguous lossless:**

- `.flac`, `.fla`, `.ape`, `.wv`, `.tta`, `.tak`
- `.wav`, `.aiff`, `.aif`, `.caf`, `.bwf`, `.au`, `.pcm`, `.raw`

**Unambiguous lossy:**

- `.mp3`, `.mp2`, `.mp1`
- `.ogg`, `.opus`, `.spx`
- `.wma`, `.wmv`, `.asf`
- `.ac3`, `.eac3`
- `.dts`, `.dtshd`, `.dtsma`
- `.aac`, `.adts`, `.loas`
- `.3gp`, `.3g2`
- `.webm`

**Ambiguous (requires Tier 3):**

- `.m4a`, `.mp4`, `.caf` — can contain either ALAC (lossless) or AAC (lossy)

### Tier 2: folder-name heuristic (zero I/O)

If the extension is ambiguous, the wrapper checks parent directory names for lossy indicators:

| Token | Example folder |
|-------|----------------|
| `aac`, `mp3`, `v0`, `v2` | `Album [320Kbps-MP3]` |
| `128k`, `192k`, `256k`, `320k` | `Artist (256kbps AAC)` |
| `lame`, `vorbis`, `opus` | `Vorbis q10` |
| `webrip`, `itunes`, `amazon` | `iTunes Plus` |
| `spotify`, `deezer`, `tidal` | `Spotify 320kbps` |

The scan stops at numeric-only directories (e.g. sequential folder names like `26005`).

### Tier 3: mutagen metadata probe (I/O required)

For files still ambiguous after Tiers 1 and 2, the wrapper reads the audio metadata using mutagen:

```python
audio = MutagenFile(file)
codec = audio.info.codec  # e.g. "alac" or "aac"
```

**Lossless codecs:**

- `flac`, `alac`, `ape`, `wavpack`, `tta`, `mlp`, `truehd`
- `pcm_*`, `shorten`, `als`, `g711`

If the codec is unknown, the probe fails and the file is treated as lossless (letting the conversion backend surface the real error).

## Actions

When a lossy file is detected, you can choose how to handle it:

### `--lossy-action leave`

Skip lossy files entirely. They appear as `SKIPPED` in the summary.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action leave
```

Output:

```
Done.  Success: 153  Skipped: 3  Failed: 0
```

### `--lossy-action copy`

Copy lossy files as-is to the output tree without transcoding.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy
```

Behaviour:

- Source file is copied (not converted)
- Sidecars are copied alongside
- No quality degradation

### `--lossy-action convert`

Transcode lossy files to the target format.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action convert
```

{{< callout type="warning" title="Additional quality loss" >}}Transcoding from a lossy source to a lossy target compounds quality loss. Only use `--lossy-action convert` if you understand the implications.{{< /callout >}}

## Skipping detection entirely

Use `--no-lossy-check` to disable lossy detection and treat all files as lossless:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --no-lossy-check
```

Use cases:

- When your source is known to be all-lossless
- For very large libraries where the pre-flight scan is slow
- When you want to force-transcode everything

Mutually exclusive with `--lossy-action`.

## Discovering lossy files

Before committing to a lossy action, you can scan and list lossy files:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
```

Output:

```
/home/user/Music/Artist/Album/track03.mp3
/home/user/Music/Artist/Album/track07.ogg
```

This exits immediately after listing, without modifying anything.

## Dry run with lossy information

The `--dry-run` flag shows all jobs including lossy status:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action leave --dry-run
```

Output:

```
Dry run — jobs that would be executed:

  /home/user/Music/Artist/Album/track01.flac -> /home/user/Converted/Artist/Album/track01.flac  [convert]
  /home/user/Music/Artist/Album/track02.flac -> /home/user/Converted/Artist/Album/track02.flac  [convert]
  /home/user/Music/Artist/Album/track03.mp3 -> /home/user/Converted/Artist/Album/track03.mp3  [skip] [LOSSY]

Total: 3 job(s)
```

## Gate behaviour

If lossy files are detected but no action is specified, the run aborts immediately:

```
Lossy source files found. You must specify --lossy-action to proceed.
Found 3 lossy file(s):
  /home/user/Music/Artist/Album/track03.mp3
  /home/user/Music/Artist/Album/track07.ogg

Add one of: --lossy-action leave | --lossy-action copy | --lossy-action convert
```

This prevents accidental transcoding of lossy sources without explicit user consent.

## Implementation details

### Detection logic

```python
def is_lossy(file: Path) -> bool:
    # Tier 1: Extension
    ext_result = _is_lossy_by_ext(file)
    if ext_result is not None:
        return ext_result

    # Tier 2: Folder name
    folder_result = _is_lossy_by_folder(file)
    if folder_result is not None:
        return folder_result

    # Tier 3: Mutagen probe
    return _is_lossy_by_mutagen(file)
```

### Thread pool for probing

Ambiguous files are probed in parallel using a thread pool:

```python
with ThreadPoolExecutor(max_workers=probe_workers) as executor:
    futures = [executor.submit(_is_lossy_by_mutagen, f) for f in ambiguous_files]
    for future in as_completed(futures):
        # Process results
```

## Index persistence

The `is_lossy` result is persisted in the temporary index database (`tmp/index.db`):

```sql
SELECT source_path, is_lossy FROM index_entries;
```

| is_lossy | Meaning |
|----------|---------|
| `1` | Lossy source detected |
| `0` | Lossless source confirmed |
| `NULL` | Not probed (`--no-lossy-check`) |

This allows future resume operations to skip re-probing.

## Best practices

1. **Use `--list-lossy` first** to see what lossy files exist before choosing an action.
2. **Prefer `--lossy-action copy`** if you want to preserve all source material without quality loss.
3. **Use `--lossy-action leave`** if you only want lossless-to-lossless conversions.
4. **Avoid `--lossy-action convert`** unless you're aware of the quality implications.
5. **Use `--no-lossy-check`** only when you're certain all sources are lossless.
