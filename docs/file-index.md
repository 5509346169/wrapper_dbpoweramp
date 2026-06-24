# File Index System

This document explains the temporary SQLite index database (`tmp/index.db`) used during conversion runs.

---

## Overview

Every conversion run builds a temporary snapshot of the discovered files in a SQLite database. This index serves as the **single source of truth** for the conversion step.

---

## Purpose

The index captures:

1. **All discovered files** - Audio files found in the input path
2. **Probe results** - Lossy/lossless classification
3. **Output paths** - Computed destination for each file
4. **Job types** - convert, copy, or skip
5. **Sidecar information** - Associated lyrics and cover files

---

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
    is_lossy     INTEGER,        -- 0/1, NULL = not probed
    created_at   TEXT NOT NULL
)
```

### Column Descriptions

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-incrementing primary key |
| `source_path` | TEXT | Absolute path to source file |
| `dest_path` | TEXT | Absolute path to output file |
| `job_type` | TEXT | "convert", "copy", or "skip" |
| `file_size` | INTEGER | File size in bytes |
| `sidecar_files` | TEXT | Newline-separated sidecar basenames |
| `mtime` | REAL | Source file modification time |
| `is_lossy` | INTEGER | 0=false, 1=true, NULL=not probed |
| `created_at` | TEXT | UTC timestamp of creation |

---

## Lifecycle

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

---

## Accessing Preserved Indexes

If a run fails or is interrupted, the index is preserved for debugging:

```sh
# List all entries
sqlite3 tmp/index.db "SELECT * FROM index_entries LIMIT 10;"

# Count by job type
sqlite3 tmp/index.db "SELECT job_type, COUNT(*) FROM index_entries GROUP BY job_type;"

# Find lossy files
sqlite3 tmp/index.db "SELECT source_path FROM index_entries WHERE is_lossy = 1;"

# Get summary
sqlite3 tmp/index.db "SELECT COUNT(*) as total, SUM(file_size) as size FROM index_entries;"
```

---

## Index-Only Mode (`--build-index`)

Build an index without converting:

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless --build-index my_index.db
```

**Output:**
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

---

## Index-Run Mode (`--index`)

Run conversions using a pre-built index:

```sh
python main.py --index my_index.db -O ~/Converted -p flac-lossless
```

**Output:**
```
Loaded index: my_index.db
  Total files: 156
  Total size: 2.4 GiB
  Lossy files: 3
```

This skips the scan and probe phases entirely, using the index directly.

**Use cases:**
- Resume after interruption
- Re-run with different settings (e.g., different workers)
- Integrate with external tools

---

## API Usage

### Creating an Index

```python
from src.index.builder import IndexBuilder
from src.index.scanner import scan_with_progress
from src.models.types import LossyAction

# Create index
index = IndexBuilder(Path("output.db"))

# Scan files
rows, _ = scan_with_progress(input_path, excludes, preset, progress)

# Enrich rows (probe, classify)
enrich_index_rows_streaming(
    scan_rows=rows,
    input_root=input_root,
    source_root=None,
    output_root=output_root,
    preset=preset,
    lossy_action=LossyAction.CONVERT,
    no_lossy_check=False,
    probe_workers=8,
    progress=progress,
    index_builder=index,
)

index.commit()
index.close()
```

### Reading an Index

```python
from src.index.builder import IndexBuilder

index = IndexBuilder.from_existing(Path("output.db"))

# Iterate rows
for row in index.iter_rows():
    print(f"Source: {row.source_path}")
    print(f"Dest: {row.dest_path}")
    print(f"Type: {row.job_type}")
    print(f"Lossy: {row.is_lossy}")

# Get summary
summary = index.get_summary()
print(f"Total: {summary['total']}")
print(f"Lossy: {summary['lossy']}")
print(f"By type: {summary['by_type']}")

index.close()
```

---

## Index Statistics

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

---

## Migration Support

The `IndexBuilder` constructor automatically handles schema migrations:

```python
# If is_lossy column doesn't exist, add it
cur = self._conn.execute("PRAGMA table_info(index_entries)")
existing_cols = {row[1] for row in cur.fetchall()}
if "is_lossy" not in existing_cols:
    self._conn.execute("ALTER TABLE index_entries ADD COLUMN is_lossy INTEGER")
```

This ensures backward compatibility with older index files.

---

## Concurrency

The index uses:

- **SQLite with WAL mode** - Safe concurrent reads
- **Thread locks** - Safe concurrent writes within the same process

Note: The index is designed for single-process use. For parallel access, use separate database connections.

---

## Storage Location

| Environment | Default Location |
|-------------|------------------|
| Normal run | `tmp/index.db` |
| `--build-index` | User-specified path |
| `--index` | User-specified path |

The `tmp/` directory is gitignored to avoid committing large index files.

---

## Manual Cleanup

To clear a stale index manually:

```sh
rm tmp/index.db
```

Or on Windows:

```powershell
Remove-Item tmp/index.db
```

---

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

### Index has NULL is_lossy values

This occurs when `--no-lossy-check` was used. The files were not probed.

### Index shows unexpected job types

Check:
- `--lossy-action` setting
- Lossy detection results
- Sidecar configuration
