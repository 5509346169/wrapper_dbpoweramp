# Roadmap

## Phase 1 — md5sum-staging (CURRENT)
**Status:** CONTEXT.md written — ready for research/planning

Implement a per-run md5sum-named temp staging layer for the native dbPoweramp
backend that:
- Triggers when source/dest has non-ASCII **or** path > 240 chars
- Names staged files `<12-hex-md5>.md5hash.<ext>`
- Persists `source -> md5sum -> temp_path -> dest` in a new `staging_cache_<sig>.db`
- Finishes with atomic `os.replace` move
- Logs `temp_filename` to history on failure

**Key files to create:**
- `src/pathing/md5_staging.py`
- `src/pathing/utf8_check.py`
- `src/index/staging_cache.py`

**Key files to modify:**
- `src/pathing/long_path.py` (replace `stage_paths`/`unstage`)
- `src/backends/native_dbpoweramp.py` (call new staging API)
- `src/app/lifecycle/tempdir.py` (cleanup scope)
- `src/history/schema.py` (add `temp_filename`)
- `src/history/conversion_db.py` (INSERT with `temp_filename`)
- `src/cli/args.py` (new `--md5-staging` flag)

**Tests to update:**
- `tests/test_tmp_staging.py`
- `tests/test_backend_quoting.py`

---

## Phase 2 — Source-File Content Hashing
Use MD5 of source file bytes (not path string) for cache hits independent of
source path. Allows re-encoding the same file content even when it moves or
gets a new name.

---

## Phase 3 — Wine Backend UTF-8 Parity
Mirror the md5sum staging approach into `wine_dbpoweramp.py` so non-ASCII
filenames work under Wine too.

---

## Phase 4 — CoreConverter Retry on qaac-Pipe Failure
Replace per-file 0-byte recovery with a single CoreConverter-level retry
(counting toward existing `--retry-failed`).

---

## Phase 5 — Parallel/Staged Verification
Use the staging cache to run post-write verification on a second thread while
the next conversion starts, overlapping I/O.