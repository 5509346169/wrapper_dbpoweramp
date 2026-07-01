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

### `--execution-mode MODE`

**Type:** String (enum)
**Required:** No
**Choices:** `hybrid`, `phased`

Execution mode for job scheduling. Overrides `execution.execution_mode` in `settings.yaml`.

| Value | Description |
|-------|-------------|
| `hybrid` | Files processed in whatever order the pool schedules them, mixing skip/copy/convert arbitrarily |
| `phased` | Files processed in strict order: skip jobs first, then copy jobs, then convert jobs |

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --execution-mode phased
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

### `--failed-only`

**Type:** Flag  
**Required:** No  
**Mutually exclusive with:** `--force`

Convert only files whose most recent history row is `FAILED`. Previously-successful files and `job_type='skip'` files are left untouched. Matched files are re-encoded even if a stale `FAILED` history row would normally short-circuit the subprocess call, so any existing or partial output file is overwritten with a fresh attempt. Useful for:

- Retrying files that broke due to a transient issue (full disk, network share offline, locked encoder DLL).
- Pushing through a batch after fixing an environment problem without re-converting the files that already succeeded.

Under the hood the prefilter bulk-queries `ConversionDB.failed_job_pairs()` for `(source, dest, job_type)` triples with `status='FAILED'` (only `convert` and `copy` job types are considered; `skip` rows are never actionable). Files matching a triple go pending; everything else goes straight to skipped.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --failed-only
```

---

### `--tmp-staging` / `--no-tmp-staging`

**Type:** Flag (mutually exclusive pair)  
**Required:** No  
**Default:** Inherited from `backend.native_dbpoweramp.tmp_staging` in `settings.yaml` (defaults to `true`)

Enable the long-path workaround for the native Windows dBpoweramp backend. When on, each conversion is staged through a short path under `./tmp/audio/`. The flow is a literal three-step copy chain:

1. `stage_paths()` does `shutil.copy2(long_source, ./tmp/audio/src/<hash>__<basename>)`.
2. CoreConverter runs and writes `tmp/audio/src/<hash>__<basename>` to `tmp/audio/dst/<hash>__<basename>`.
3. `unstage()` does `shutil.copy2(tmp/audio/dst/<hash>__<basename>, long_destination)`, then unlinks both the staged output and the staged source.

This avoids every `CreateFileW` MAX_PATH-sensitive call inside CoreConverter and its child encoders (e.g. `qaac.exe`) regardless of whether 8.3 name generation is enabled on the volume. Staging only kicks in for paths over ~240 chars, so short paths pay no I/O cost. Off by default on non-Windows platforms (no-op).

> Note: the final step uses `copy2`, not `move`, so the staged output stays on disk during the copy — if the destination volume fills up mid-write, the staged file is still recoverable in `tmp/audio/dst/` for inspection.

Use `--no-tmp-staging` to override `settings.yaml` and pass long paths straight to CoreConverter (not recommended for deeply nested JP/en libraries).

```sh
# Default behaviour (inherits true from settings.yaml).
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --tmp-staging

# Force off.
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --no-tmp-staging
```

Pair with `--db` if your history lives somewhere other than the default location.

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

### `--verify-output MODE`

**Type:** String (enum)  
**Required:** No  
**Choices:** `none`, `full`  
**Default:** `full`

Post-conversion integrity check mode. `full` (default) runs a full-frame decode on every `convert` output via `soundfile` / `miniaudio` / `mutagen`. `none` keeps the legacy existence + non-zero-size check only.

```sh
# Default: full integrity check (every file is decoded)
python main.py -I ~/Music -O ~/Converted -p flac-lossless

# Skip the integrity check (legacy mode)
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-output none
```

When a full-frame decode detects corruption, the output line reads:

```
[verify] Not - Truncated output: declared 10240 frames, decoded 5120 frames
```

The job is marked `FAILED` with that reason in the history database.

---

### `--verify-skip`

**Type:** Flag  
**Required:** No

Pre-verify skip candidates: before honouring a `SUCCESS` history row for a `convert` or `copy` job, re-decode the on-disk output via `src.audio.integrity.verify_file`. If the output decodes as `NOT_OK`, the job is demoted from `SKIP` to `CONVERT` (the pipeline re-runs it) and the original `SUCCESS` row is overwritten with the new result.

Off by default — pre-verify adds a full-frame decode to every skip candidate, which can dominate runtime on large libraries.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-skip
```

---

### `--db-version`

**Type:** Flag  
**Required:** No

Print the history database schema version and exit before the pipeline starts. Useful for checking whether a migration is needed.

```sh
python main.py --db-version
```

**Sample output:**
```
History DB:    conversion_history.db
Schema:        v2 (up-to-date)
Target:        v2
Last migrated: 2026-06-28 14:30:00 UTC
Backups:       1 file on disk (conversion_history.db.bak-2026-06-28T14:30:00Z)
```

---

## DB Inspection Subcommands

### `python main.py db check`

Print schema version, audit history, and backup status, then exit 0.

```sh
python main.py db check
python main.py db check --db-path /path/to/history.db
python main.py db check --db /path/to/history.db     # alias for --db-path
python main.py --db /path/to/history.db db check      # top-level --db (must precede the subcommand keyword)
```

The `--db` flag is an alias for `--db-path` on this subcommand. When passed at the top level (e.g. `--db <path> db check`), argparse forwards it to the `db` dispatcher, which falls through to `args.db` if `args.db_path` is unset.

**Sample output:**
```
History DB:    /path/to/history.db
Schema:        v2 (up-to-date)
Target:        v2
Last migrated: 2026-06-28 14:30:00 UTC  (audit row #2)
Backups:       1 file on disk (history.db.bak-2026-06-28T14:30:00Z, 18.4 MiB)
```

### `python main.py db migrate`

Force-migrate the history database to the latest schema. The migration auto-runs on first conversion anyway; this subcommand is for recovering from a failed or skipped migration.

```sh
python main.py db migrate
python main.py db migrate --db-path /path/to/history.db
python main.py db migrate --db /path/to/history.db
python main.py --db /path/to/history.db db migrate
```

A backup of the form `<db>.bak-<UTCISO>` is created before any migration runs.

### `python main.py db doctor`

Like `db check`, but also probes for orphaned `.bak` files and schema drift.

```sh
python main.py db doctor
python main.py db doctor --db-path /path/to/history.db
python main.py db doctor --db /path/to/history.db
python main.py --db /path/to/history.db db doctor
```

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
| `--execution-mode` | No | `hybrid` or `phased` execution |
| `-v`, `--verbose` | No | Verbose output |
| `--exclude` | No | Exclude folders (repeatable) |
| `--db` | No | History database path |
| `--force` | No | Ignore resume history |
| `--failed-only` | No | Convert only files whose latest history row is `FAILED` (overwrites output) |
| `--tmp-staging` / `--no-tmp-staging` | No | Enable/disable long-path workaround via `./tmp/audio/` staging (native Windows backend only) |
| `--dry-run` | No | List jobs without converting |
| `--list-lossy` | No | Print lossy files and exit |
| `--build-index` | No | Build index to file |
| `--index` | No | Use pre-built index |
| `--verify-output` | No | Post-convert integrity check mode (`none`\|`full`) |
| `--verify-skip` | No | Pre-verify skip candidates before honouring history |
| `--db-version` | No | Print DB schema version and exit |
| `db {check,migrate,doctor}` | No | Inspect or migrate the history database |
| `-v`, `--verbose` | No | Verbose output |

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

### Verify integrity post-conversion

```sh
# Full integrity check (default — every converted file is decoded)
python main.py -I ~/Music -O ~/Converted -p flac-lossless
# Output lines may include:
#   [verify] Okay
#   [verify] Not - Truncated output: declared 10240 frames, decoded 5120 frames

# Skip integrity check (legacy mode)
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-output none
```

### Re-decode skip candidates before trusting them

```sh
# Pre-verify: demotes corrupt skip candidates to pending (will be reconverted)
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-skip
```

### Check history DB schema before running

```sh
python main.py --db-version
```

### Force a schema migration

```sh
python main.py db migrate --db-path conversion_history.db
```
