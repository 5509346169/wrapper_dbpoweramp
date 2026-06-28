---
permalink: /file-index/
layout: default
title: File Index System
slug: file-index
category: engineering
order: 10
summary: The tmp/index.db temporary SQLite snapshot and its lifecycle.
audience: [engineer]
---

This document explains the temporary SQLite index database (`tmp/index.db`) used during conversion runs.

## Overview

Every conversion run builds a temporary snapshot of the discovered files in a SQLite database. This index serves as the single source of truth for the conversion step.

## Purpose

The index captures:

1. **All discovered files** — audio files found in the input path
2. **Probe results** — lossy/lossless classification
3. **Output paths** — computed destination for each file
4. **Job types** — convert, copy, or skip
5. **Sidecar information** — associated lyrics and cover files

The companion scan cache (`./tmp/scan_cache_*.db`) captures columns 1 and 5 only (path + size + mtime + sidecar) so the filesystem walk can be skipped on subsequent runs.

## Schema

```sql
CREATE TABLE index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path  TEXT NOT NULL,
    dest_path    TEXT NOT NULL,
    job_type     TEXT NOT NULL,
    file_size    INTEGER NOT NULL,
    sidecar_files TEXT NOT NULL,
    mtime        REAL NOT NULL,
    is_lossy     INTEGER,
    created_at   TEXT NOT NULL
)
```

### Column descriptions

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-incrementing primary key |
| `source_path` | TEXT | Absolute path to source file |
| `dest_path` | TEXT | Absolute path to output file |
| `job_type` | TEXT | `convert`, `copy`, or `skip` |
| `file_size` | INTEGER | File size in bytes |
| `sidecar_files` | TEXT | Newline-separated sidecar basenames |
| `mtime` | REAL | Source file modification time |
| `is_lossy` | INTEGER | `0` = lossless, `1` = lossy, `NULL` = not probed |
| `created_at` | TEXT | UTC timestamp of creation |

## Lifecycle

### Scan cache

Before the full index, the tool tries to reuse a per-run scan cache stored in `./tmp/scan_cache_*.db`. This cache stores only the path + size + mtime + sidecar columns — no probe results — so the probe phase is never influenced by stale data.

```text
Input + Excludes  ──►  sha256(...)[:16]  ──►  scan_cache_<ts>_<sig>.db
```

The cache is created fresh each time the directory is walked, and the filename includes the input signature so `open_latest()` can verify the cache matches the current CLI args before trusting it. Pass `--no-scan-cache` to disable and always walk the filesystem.

```sh
# First run: full walk, cache is written
python main.py -I ~/Music -p qaac-cvbr-256
  [Scanning] ...           # cache miss, walk happens
  [Probing]  ...           # mutagen opens every file
  ...

# Second run: walk is skipped entirely
python main.py -I ~/Music -p qaac-cvbr-256
  [Scanning (cached)]  1234/1234  [cached]  # cache hit
  [Probing]  ...           # still runs — lossy status not cached
  ...
```

Cache lifecycle:

- **Written by:** scan phase (when cache misses)
- **Read by:** scan phase on subsequent runs (when cache hits)
- **Never deleted** automatically — it's a persistent snapshot. Delete manually with `rm ./tmp/scan_cache_*.db` to force a fresh walk.
- The `--no-scan-cache` flag skips both read and write of the cache.

The scan cache does **not** cache probe results, so post-convert verification runs from scratch on every run that actually transcodes a file. The `--no-scan-cache` flag only affects the directory walk, not the verify step.

### Creation

The index is created at the beginning of the scan phase:

```python
index_db_path = Path("tmp/index.db")
index_builder = IndexBuilder(index_db_path)
```

The `tmp/` directory is created automatically if it doesn't exist.

### Population

Rows are written incrementally during the probe phase:

```python
for row in rows:
    index_builder.add(row)
    progress.advance()

index_builder.commit()
```

This provides a real-time snapshot of the scan progress.

### Preservation

The index is preserved (not deleted) if:

- Any job failed
- An exception occurred
- The run was interrupted (Ctrl+C/SIGTERM)

```
[yellow]Index preserved:[/yellow] tmp/index.db
  Hint: sqlite3 tmp/index.db "SELECT * FROM index_entries LIMIT 10;"
```

### Cleanup

The index is deleted if:

- All jobs succeeded
- No exception occurred
- The run completed normally

## Accessing preserved indexes

If a run fails or is interrupted, the index is preserved for debugging:

```sh
sqlite3 tmp/index.db "SELECT * FROM index_entries LIMIT 10;"
sqlite3 tmp/index.db "SELECT job_type, COUNT(*) FROM index_entries GROUP BY job_type;"
sqlite3 tmp/index.db "SELECT source_path FROM index_entries WHERE is_lossy = 1;"
sqlite3 tmp/index.db "SELECT COUNT(*) as total, SUM(file_size) as size FROM index_entries;"
```

## Index-only mode (`--build-index`)

Build an index without converting:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --build-index my_index.db
```

Output:

```
Index built successfully: my_index.db
  Total files: 156
  Total size: 2.4 GiB
  Lossy files: 3
  convert: 153
```

This is useful for:

- Pre-scanning large libraries
- Inspecting probe results before committing to conversion
- Batch processing with custom scripts

## Index-run mode (`--index`)

Run conversions using a pre-built index:

```sh
python main.py --index my_index.db -O ~/Converted -p flac-lossless
```

Output:

```
Loaded index: my_index.db
  Total files: 156
  Total size: 2.4 GiB
  Lossy files: 3
```

This skips the scan and probe phases entirely, using the index directly.

Use cases:

- Resume after interruption
- Re-run with different settings (e.g. different workers)
- Integrate with external tools

## Verification interaction

Post-convert integrity verification (`--verify-output full`) and pre-verify (`--verify-skip`) operate on the output files as they exist on disk; they have no interaction with the scan cache. The `--build-index` and `--index` modes do not run verification when no transcoding occurs, but `--verify-skip` does run inside `--index` mode when the pre-filter classifies a job as a skip candidate.

## Index statistics

The `get_summary()` method returns aggregated statistics:

```python
summary = index_builder.get_summary()
# {
#     "total": 156,
#     "lossy": 3,
#     "by_type": {"convert": 153},
#     "total_bytes": 2576980377,
# }
```

## Migration support

The `IndexBuilder` constructor automatically handles schema migrations:

```python
# If is_lossy column doesn't exist, add it
cur = self._conn.execute("PRAGMA table_info(index_entries)")
existing_cols = {row[1] for row in cur.fetchall()}
if "is_lossy" not in existing_cols:
    self._conn.execute("ALTER TABLE index_entries ADD COLUMN is_lossy INTEGER")
```

This ensures backward compatibility with older index files.

## Concurrency

The index uses:

- **SQLite with WAL mode** — safe concurrent reads
- **Thread locks** — safe concurrent writes within the same process

{% include components/callout.html type="note" title="Single-process" content="The index is designed for single-process use. For parallel access, use separate database connections." %}

## Storage location

| Mode | Default location |
|------|------------------|
| Normal run | `tmp/index.db` |
| `--build-index` | User-specified path |
| `--index` | User-specified path |

The `tmp/` directory is gitignored to avoid committing large index files.

## Manual cleanup

To clear a stale index manually:

```sh
rm tmp/index.db
```

Or on Windows:

```powershell
Remove-Item tmp/index.db
```

## Troubleshooting

### Index not deleted after successful run

This indicates either:

- A job failed
- An exception occurred
- The run was interrupted

Check the run output for errors or warnings.

### Index still empty after scan

This indicates the probe phase encountered errors. Check:

- File permissions
- Corrupted audio files
- Missing mutagen support for file format

### Index has NULL `is_lossy` values

This occurs when `--no-lossy-check` was used. The files were not probed.

### Index shows unexpected job types

Check:

- `--lossy-action` setting
- Lossy detection results
- Sidecar configuration
