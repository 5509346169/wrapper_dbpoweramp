---
permalink: /cli/
layout: default
title: Command-Line Interface
slug: cli
category: configuration
order: 20
summary: Every CLI flag, option, and DB subcommand grouped by purpose.
audience: [user, engineer]
---

This document provides a complete reference for all command-line flags, options, and arguments.

## Usage

```sh
python main.py -I INPUT -O OUTPUT -p PRESET [OPTIONS]
```

## Required arguments

### `-I, --input PATH`

| Property | Value |
|----------|-------|
| Type | Path (file or directory) |
| Required | Yes |

The file or directory to convert.

```sh
python main.py -I song.flac -O ./output -p flac-lossless
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

### `-O, --output PATH`

| Property | Value |
|----------|-------|
| Type | Path (directory) |
| Required | Yes |

The output root directory. The directory structure is preserved relative to the input.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
# ~/Music/Artist/Album/track.flac -> ~/Converted/Artist/Album/track.flac
```

### `-p, --preset NAME`

| Property | Value |
|----------|-------|
| Type | String |
| Required | Yes |

Preset name from `presets.yaml`. Available presets:

| Preset | Output Format |
|--------|---------------|
| `flac-lossless` | FLAC (compression level 5) |
| `mp3-v0-vbr` | MP3 V0 VBR |
| `mp3-320-cbr` | MP3 320 kbps CBR |
| `aac-vbr-high` | AAC VBR high quality |
| `qaac-cvbr-256` | AAC 256 kbps via QAAC |
| `opus-128` | Opus 128 kbps |

## Backend selection

### `--source-path PATH`

| Property | Value |
|----------|-------|
| Type | Path (directory) |
| Required | No |

Root for relative-path computation. When provided, the output path is computed relative to this path rather than the input path.

```sh
python main.py -I ~/Music/Artist/Album -O ~/Converted \
    --source-path ~/Music \
    -p flac-lossless
```

`--source-path` must be an ancestor of `--input`.

### `--backend NAME`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Required | No |
| Choices | `wine_dbpoweramp`, `native_dbpoweramp`, `native_ffmpeg` |

Override the backend selection. When not specified, the backend is determined by `settings.yaml` defaults and auto-detection.

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### `--auto-detect-backend`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Enable automatic backend detection, overriding any `--backend` setting. Forces the auto-detect logic to run.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --auto-detect-backend
```

### `--no-auto-detect-backend`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Disable automatic backend detection. Forces the use of `backend.default` from `settings.yaml`.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --no-auto-detect-backend
```

## Lossy policy

### `--lossy-action ACTION`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Required | Conditional |
| Choices | `leave`, `copy`, `convert` |

What to do with lossy source files. Required if any lossy source files are detected.

| Action | Description |
|--------|-------------|
| `leave` | Skip lossy files; they appear as `SKIPPED` in the summary |
| `copy` | Copy lossy files as-is to the output tree (no transcoding) |
| `convert` | Transcode lossy sources to the target format |

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action leave
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action convert
```

Mutually exclusive with `--no-lossy-check`, `--dry-run`, and `--list-lossy`.

### `--no-lossy-check`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Disable lossy detection entirely. All files are treated as lossless and will be transcoded.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --no-lossy-check
```

Mutually exclusive with `--lossy-action`.

### `--list-lossy`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Scan and print lossy files found, then exit. Useful for deciding which policy to use before running the full batch.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --list-lossy
```

Mutually exclusive with `--lossy-action`, `--index`, and `--build-index`.

## Execution

### `-w, --workers N`

| Property | Value |
|----------|-------|
| Type | Integer |
| Required | No |

Override the number of parallel workers from `settings.yaml`.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8
```

### `--worker-model MODEL`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Required | No |
| Choices | `thread`, `process` |

| Model | Description |
|-------|-------------|
| `thread` | `ThreadPoolExecutor` — threads share memory |
| `process` | `ProcessPoolExecutor` — separate processes |

### `--execution-mode MODE`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Required | No |
| Choices | `hybrid`, `phased` |

| Value | Description |
|-------|-------------|
| `hybrid` | Files processed in whatever order the pool schedules them, mixing skip/copy/convert arbitrarily |
| `phased` | Files processed in strict order: skip jobs first, then copy jobs, then convert jobs |

### `--exclude DIR`

| Property | Value |
|----------|-------|
| Type | String |
| Required | No (repeatable) |

Folder names to exclude from conversion. Can be specified multiple times.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless \
    --exclude "_UNPROCESSED" \
    --exclude "Lossy" \
    --exclude "Temporary"
```

## Inspection

### `-v, --verbose`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Enable live verbose conversion stream. Shows each line of output from the conversion tool.

### `--dry-run`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Build and print the job list without converting anything.

```
Dry run — jobs that would be executed:

  /home/user/Music/Artist/Album/track01.flac -> /home/user/Converted/Artist/Album/track01.flac  [convert]
  /home/user/Music/Artist/Album/track02.flac -> /home/user/Converted/Artist/Album/track02.flac  [convert]
  /home/user/Music/Artist/Album/track03.mp3 -> /home/user/Converted/Artist/Album/track03.mp3  [convert] [LOSSY]

Total: 3 job(s)
```

Mutually exclusive with `--lossy-action`, `--index`, and `--build-index`.

### `--build-index PATH`

| Property | Value |
|----------|-------|
| Type | Path |
| Required | No |

Build and save index database without converting, then exit.

### `--index PATH`

| Property | Value |
|----------|-------|
| Type | Path |
| Required | No |

Use a pre-built index database as input, skipping filesystem scan and probe phases.

## Verification

{#output-verification}
### `--verify-output MODE`

| Property | Value |
|----------|-------|
| Type | String (enum) |
| Required | No |
| Choices | `none`, `full` |
| Default | `full` |

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

### `--verify-skip`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Pre-verify skip candidates: before honouring a `SUCCESS` history row for a `convert` or `copy` job, re-decode the on-disk output via `src.audio.integrity.verify_file`. If the output decodes as `NOT_OK`, the job is demoted from `SKIP` to `CONVERT` (the pipeline re-runs it) and the original `SUCCESS` row is overwritten with the new result.

Off by default — pre-verify adds a full-frame decode to every skip candidate, which can dominate runtime on large libraries.

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-skip
```

See [Workflow](/workflow/#pre-verify-skip-gate) for the demotion policy.

## DB inspection

{#db-inspection-cli}
### `--db-version`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Print the history database schema version and exit before the pipeline starts.

```sh
python main.py --db-version
```

Sample output:

```
History DB:    conversion_history.db
Schema:        v2 (up-to-date)
Target:        v2
Last migrated: 2026-06-28 14:30:00 UTC
Backups:       1 file on disk (conversion_history.db.bak-2026-06-28T14:30:00Z)
```

### `python main.py db check`

Print schema version, audit history, and backup status, then exit 0.

```sh
python main.py db check
python main.py db check --db-path /path/to/history.db
python main.py db check --db /path/to/history.db     # alias for --db-path
python main.py --db /path/to/history.db db check      # top-level --db (must precede the subcommand keyword)
```

The `--db` flag is an alias for `--db-path` on this subcommand. When passed at the top level, argparse forwards it to the `db` dispatcher, which falls through to `args.db` if `args.db_path` is unset.

Sample output:

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

## History

### `--db PATH`

| Property | Value |
|----------|-------|
| Type | Path |
| Required | No |

Override the history database path from `settings.yaml`.

## Resume

### `--force`

| Property | Value |
|----------|-------|
| Type | Flag |
| Required | No |

Ignore resume history and reconvert everything. By default, already-converted files are skipped.

## Quick reference

| Flag | Required | Description |
|------|----------|-------------|
| `-I`, `--input` | Yes | File or directory to convert |
| `-O`, `--output` | Yes | Output root directory |
| `-p`, `--preset` | Yes | Preset name |
| `--source-path` | No | Root for relative-path math |
| `--backend` | No | Backend override |
| `--auto-detect-backend` | No | Force auto-detection |
| `--no-auto-detect-backend` | No | Disable auto-detection |
| `--lossy-action` | Conditional* | Lossy source handling |
| `--no-lossy-check` | No | Disable lossy detection |
| `-w`, `--workers` | No | Number of workers |
| `--worker-model` | No | Thread or process pool |
| `--execution-mode` | No | `hybrid` or `phased` |
| `-v`, `--verbose` | No | Verbose output |
| `--exclude` | No | Exclude folders (repeatable) |
| `--db` | No | History database path |
| `--force` | No | Ignore resume history |
| `--dry-run` | No | List jobs without converting |
| `--list-lossy` | No | Print lossy files and exit |
| `--build-index` | No | Build index to file |
| `--index` | No | Use pre-built index |
| `--verify-output` | No | Post-convert integrity check mode (`none`\|`full`) |
| `--verify-skip` | No | Pre-verify skip candidates |
| `--db-version` | No | Print DB schema version and exit |
| `db {check,migrate,doctor}` | No | Inspect or migrate the history database |

\* Required if lossy source files are detected.

## Examples

### Basic conversion

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

### MP3 with verbose output

```sh
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr -v
```

### Excluding folders

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless \
    --exclude "Lossy" \
    --exclude "Podcasts"
```

### Using dBpoweramp backend

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Copying lossy files

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --lossy-action copy
```

### Parallel processing

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless -w 8 --worker-model process
```

### Resume with index

```sh
# Step 1: run (gets interrupted)
python main.py -I ~/Music -O ~/Converted -p flac-lossless

# Step 2: resume from preserved index
python main.py --index tmp/index.db -O ~/Converted -p flac-lossless
```

### Verify integrity post-conversion

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --verify-output none
```

### Re-decode skip candidates

```sh
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
