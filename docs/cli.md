# Command-Line Interface Reference

This document provides a complete reference for all command-line flags, options, and arguments.

---

## Usage

```sh
python main.py -I INPUT -O OUTPUT -p PRESET [OPTIONS]
```

---

## Required Arguments

### `-I, --input PATH`

**Type:** Path (file or directory)  
**Required:** Yes

The file or directory to convert.

```sh
# Single file
python main.py -I song.flac -O ./output -p flac-lossless

# Directory
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

---

### `-O, --output PATH`

**Type:** Path (directory)  
**Required:** Yes

The output root directory. The directory structure is preserved relative to the input.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
# ~/Music/Artist/Album/track.flac -> ~/Converted/Artist/Album/track.flac
```

---

### `-p, --preset NAME`

**Type:** String  
**Required:** Yes

Preset name from `presets.yaml`. Available presets:

| Preset | Output Format |
|--------|--------------|
| `flac-lossless` | FLAC (compression level 5) |
| `mp3-v0-vbr` | MP3 V0 VBR |
| `mp3-320-cbr` | MP3 320 kbps CBR |
| `aac-vbr-high` | AAC VBR high quality |
| `qaac-cvbr-256` | AAC 256 kbps via QAAC |
| `opus-128` | Opus 128 kbps |

```sh
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr
```

---

## Optional Arguments

### `--source-path PATH`

**Type:** Path (directory)  
**Required:** No

Root for relative-path computation. When provided, the output path is computed relative to this path rather than the input path.

Useful for extracting a subdirectory while preserving the full library structure:

```sh
# Convert ~/Music/Artist/Album but output ~/Converted/Artist/Album
python main.py -I ~/Music/Artist/Album -O ~/Converted \
    --source-path ~/Music \
    -p flac-lossless

# Output: ~/Converted/Artist/Album/track.flac
```

**Validation:** `--source-path` must be an ancestor of `--input`.

---

### `--backend NAME`

**Type:** String (enum)  
**Required:** No  
**Choices:** `wine_dbpoweramp`, `native_dbpoweramp`, `native_ffmpeg`

Override the backend selection. When not specified, the backend is determined by `settings.yaml` defaults and auto-detection.

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

**Related:** `--auto-detect-backend`, `--no-auto-detect-backend`

---

### `--auto-detect-backend`

**Type:** Flag  
**Required:** No

Enable automatic backend detection, overriding any `--backend` setting. This forces the auto-detect logic to run.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --auto-detect-backend
```

On Windows with dBpoweramp installed, this will use `native_dbpoweramp`.

---

### `--no-auto-detect-backend`

**Type:** Flag  
**Required:** No

Disable automatic backend detection. This forces the use of `backend.default` from `settings.yaml`.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --no-auto-detect-backend
```

---

### `--lossy-action ACTION`

**Type:** String (enum)  
**Required:** Conditional  
**Choices:** `leave`, `copy`, `convert`

What to do with lossy source files. **Required** if any lossy source files are detected.

| Action | Description |
|--------|-------------|
| `leave` | Skip lossy files; they appear as `SKIPPED` in the summary |
| `copy` | Copy lossy files as-is to the output tree (no transcoding) |
| `convert` | Transcode lossy sources to the target format |

```sh
# Skip lossy files
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action leave

# Copy lossy files as-is
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy

# Transcode lossy files
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action convert
```

**Note:** Mutually exclusive with `--no-lossy-check`, `--dry-run`, and `--list-lossy`.

---

### `--no-lossy-check`

**Type:** Flag  
**Required:** No

Disable lossy detection entirely. All files are treated as lossless and will be transcoded.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --no-lossy-check
```

**Use case:** When your source is all-lossless and you want to skip the pre-flight scan on very large libraries.

**Note:** Mutually exclusive with `--lossy-action`.

---

### `-w, --workers N`

**Type:** Integer  
**Required:** No

Override the number of parallel workers from `settings.yaml`.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8
```

---

### `--worker-model MODEL`

**Type:** String (enum)  
**Required:** No  
**Choices:** `thread`, `process`

Override the worker pool model from `settings.yaml`.

| Model | Description |
|-------|-------------|
| `thread` | `ThreadPoolExecutor` - threads share memory |
| `process` | `ProcessPoolExecutor` - separate processes |

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --worker-model process
```

---

### `-v, --verbose`

**Type:** Flag  
**Required:** No

Enable live verbose conversion stream. Shows each line of output from the conversion tool.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -v
```

---

### `--exclude DIR`

**Type:** String  
**Required:** No (repeatable)

Folder names to exclude from conversion. Can be specified multiple times.

```sh
# Exclude single folder
python main.py -I ~/Music -O ~/Converted -p flac-lossless --exclude "_UNPROCESSED"

# Exclude multiple folders
python main.py -I ~/Music -O ~/Converted -p flac-lossless \
    --exclude "_UNPROCESSED" \
    --exclude "Lossy" \
    --exclude "Temporary"
```

---

### `--db PATH`

**Type:** Path  
**Required:** No

Override the history database path from `settings.yaml`.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --db /path/to/history.db
```

---

### `--force`

**Type:** Flag  
**Required:** No

Ignore resume history and reconvert everything. By default, already-converted files are skipped.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --force
```

---

### `--dry-run`

**Type:** Flag  
**Required:** No

Build and print the job list without converting anything.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --dry-run
```

**Output example:**
```
Dry run — jobs that would be executed:

  /home/user/Music/Artist/Album/track01.flac -> /home/user/Converted/Artist/Album/track01.flac  [convert]
  /home/user/Music/Artist/Album/track02.flac -> /home/user/Converted/Artist/Album/track02.flac  [convert]
  /home/user/Music/Artist/Album/track03.mp3 -> /home/user/Converted/Artist/Album/track03.mp3  [convert] [LOSSY]

Total: 3 job(s)
```

**Note:** Mutually exclusive with `--lossy-action`, `--index`, and `--build-index`.

---

### `--list-lossy`

**Type:** Flag  
**Required:** No

Scan and print lossy files found, then exit. Useful for deciding which policy to use before running the full batch.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
```

**Output example:**
```
/home/user/Music/Artist/Album/track03.mp3
/home/user/Music/Artist/Album/track07.ogg
```

**Note:** Mutually exclusive with `--lossy-action`, `--index`, and `--build-index`.

---

### `--build-index PATH`

**Type:** Path  
**Required:** No

Build and save index database without converting, then exit.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --build-index my_index.db
```

**Use case:** Pre-build an index for later use with `--index`.

**Note:** Mutually exclusive with `--index`, `--dry-run`, and `--list-lossy`.

---

### `--index PATH`

**Type:** Path  
**Required:** No

Use a pre-built index database as input, skipping filesystem scan and probe phases.

```sh
python main.py --index my_index.db -O ~/Converted -p flac-lossless
```

**Use case:** Resume a run using a previously preserved index.

**Note:** The index must exist. Mutually exclusive with `--build-index`, `--dry-run`, and `--list-lossy`.

---

## Quick Reference

| Flag | Required | Description |
|------|----------|-------------|
| `-I`, `--input` | **Yes** | File or directory to convert |
| `-O`, `--output` | **Yes** | Output root directory |
| `-p`, `--preset` | **Yes** | Preset name |
| `--source-path` | No | Root for relative-path math |
| `--backend` | No | Backend override |
| `--auto-detect-backend` | No | Force auto-detection |
| `--no-auto-detect-backend` | No | Disable auto-detection |
| `--lossy-action` | Conditional* | Lossy source handling |
| `--no-lossy-check` | No | Disable lossy detection |
| `-w`, `--workers` | No | Number of workers |
| `--worker-model` | No | Thread or process pool |
| `-v`, `--verbose` | No | Verbose output |
| `--exclude` | No | Exclude folders (repeatable) |
| `--db` | No | History database path |
| `--force` | No | Ignore resume history |
| `--dry-run` | No | List jobs without converting |
| `--list-lossy` | No | Print lossy files and exit |
| `--build-index` | No | Build index to file |
| `--index` | No | Use pre-built index |

*Required if lossy source files are detected.

---

## Examples

### Basic Conversion

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

### MP3 Encoding with Verbose Output

```sh
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr -v
```

### Excluding Folders

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless \
    --exclude "Lossy" \
    --exclude "Podcasts"
```

### Using dBpoweramp Backend

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Copying Lossy Files

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy
```

### Parallel Processing

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8 --worker-model process
```

### Resume with Index

```sh
# Step 1: Run (gets interrupted)
python main.py -I ~/Music -O ~/Converted -p flac-lossless

# Step 2: Resume from preserved index
python main.py --index tmp/index.db -O ~/Converted -p flac-lossless
```
