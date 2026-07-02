# Phase: md5sum Temp-Staging Redesign (UTF-8 + MAX_PATH)

## Goal

Replace the conditional long-path-only tmp staging in `src/pathing/long_path.py`
with a **per-run, md5sum-named temp staging layer** that:

1. Fires on the native dbPoweramp backend whenever the source/dest path would
   trip qaac / CoreConverter's UTF-8 handling **or** the 240-char safety
   threshold.
2. Persists the `source_path -> md5sum -> temp_path -> dest_path` mapping into
   a new scan-cache table so subsequent runs can recover/reuse the staging
   association without re-discovering.
3. Finishes with an **atomic move** of the converted temp file into the final
   destination (not a copy).

The existing scan-cache (per-run, input-signature-keyed) is **untouched**;
this phase adds a sibling cache.

---

## Trigger Conditions

| Decision | Choice |
|---|---|
| When does md5sum staging activate? | When source/dest **name** has non-ASCII chars (UTF-8 risk to qaac/CoreConverter) OR path > `_MAX_PATH_SAFE` (240). |
| UTF-8 detection | `Path.name.encode('ascii', 'strict')` on **both** `job.infile` and `job.outfile` raises `UnicodeEncodeError` -> stage. |
| Backend scope | **Native dbPoweramp only** (`native_dbpoweramp.py`). Wine and ffmpeg keep their existing path strategies. |
| Staged temp filename | `<md5sum>.md5hash.<ext>` — the **`.md5hash.` marker is a literal substring** in the name so a human can identify staged artefacts at a glance. |

The current `_short_hash` / `_path_is_long` logic in `src/pathing/long_path.py`
is replaced; the old `<hash>__<basename>` form is gone.

---

## Cross-Run File Identity

| Decision | Choice |
|---|---|
| What is hashed? | **MD5 of the full source path string** (UTF-8 encoded). Identical to today's `_short_hash` semantic, but extended to 12 hex chars. |
| Hash length | **12 hex chars** (1-in-16T collision space — safe for libraries of <100k files). |
| Scope | **Per-job within a run**. Two jobs in the same run that share a source path get the same md5sum; jobs in different runs that share a source path also get the same md5sum. |
| Collision policy | If `tmp/audio/src/<md5>.md5hash.<ext>` already exists from a prior run, append a random 4-hex-char suffix (`<md5>-a3f7.md5hash.<ext>`). The original md5sum stays canonical in the cache; the actual filename is recorded in the cache column. |

---

## Scan-Cache Schema Changes

| Decision | Choice |
|---|---|
| Cache location | **Separate sibling DB** to the scan-cache: `tmp/staging_cache_<input_sig>.db`. Independent of `scan_cache_<ts>_<sig>.db` so scan-cache lifecycle (new file per run) doesn't drag staging mapping along. |
| New table | `staged_jobs` — keyed by `(input_signature TEXT, md5sum TEXT)` for cheap re-lookup. |
| New columns | `source_path TEXT NOT NULL`, `md5sum TEXT NOT NULL`, `dest_path TEXT NOT NULL`, `temp_infile TEXT NOT NULL`, `temp_outfile TEXT NOT NULL`, `temp_filename TEXT NOT NULL` (the actual on-disk name including any collision suffix), `status TEXT NOT NULL DEFAULT 'PENDING'` (PENDING / SUCCESS / FAILED), `last_seen_at TEXT NOT NULL`, `attempt_count INTEGER NOT NULL DEFAULT 0`, `error_msg TEXT`. |
| Debug table | `staged_jobs_debug` — append-only log of `(md5sum, ts, event, detail)` for triage. |
| Lifecycle | `cleanup_staging_workspace()` (existing) wipes `tmp/audio/src/` and `tmp/audio/dst/` at the **start** of each run. Cache is **rebuilt** at scan time from `IndexRow.source_path` so it never goes stale. |
| Recovery on missing cache | Recompute md5sum deterministically from `source_path` via `hashlib.md5(str(source_path).encode('utf-8')).hexdigest()[:12]`. The cache is an optimisation, not a source of truth. |

---

## Post-Conversion Transfer

| Decision | Choice |
|---|---|
| Transfer method | **`os.replace`** (atomic rename, instant on same volume). On `OSError` cross-volume, fall back to `shutil.copy2` + unlink (existing `unstage` pattern). |
| Long-destination behaviour | If `dest_path` is still >260 chars after the move, **fail the job with a clear error** ("destination exceeds MAX_PATH: ...") — don't attempt a second-stage rename. |
| Mid-run failure | Mark the cache row `status='FAILED'` with `error_msg`; **leave both staged files on disk**. The next run's `cleanup_staging_workspace()` will sweep them, and a fresh copy of the source will be re-staged from disk. |
| Logging | **History DB** gains a `temp_filename TEXT` column (nullable). **Cache** has `staged_jobs_debug`. On failure both are populated; on success only `temp_filename` is set. |

---

## Decisions Locked For Research / Planning

1. New file `src/pathing/md5_staging.py` replaces the staging logic in
   `src/pathing/long_path.py`. `long_path.py` becomes a compatibility
   shim that delegates.
2. New file `src/index/staging_cache.py` defines the new `StagingCache`
   class (open/create/upsert/mark_status/iter).
3. New file `src/pathing/utf8_check.py` exposes `name_needs_staging(path)`
   for the trigger test.
4. New CLI flag `--md5-staging` (default `auto`: fire when name has
   non-ASCII OR path > 240) lives alongside the existing `--tmp-staging`.
   The two are not mutually exclusive: `--tmp-staging=off` disables the
   whole layer; `--md5-staging=off` disables only the md5sum naming
   (paths still flow through staging for the long-path case).
5. New schema migration adds `temp_filename TEXT` to `history`.
6. The native backend (`src/backends/native_dbpoweramp.py`) calls
   `stage_paths_v2()` instead of the current `stage_paths()`.
7. The conversion DB INSERT statement gains the `temp_filename` column.

---

## Deferred Ideas (Captured, Not In Scope)

- Source-file **content** hashing (MD5 of bytes) for cache hits independent
  of path — would let re-encoding the same file skip work. Own phase.
- Parallel/staged verification using the cache — own phase.
- Removing the per-file 0-byte qaac-pipe recovery in favour of a single
  CoreConverter-level retry. Own phase.
- Wine backend UTF-8 staging parity — own phase.

---

## Open Risks

- **Cross-volume `os.replace`** failure path is rare on Windows (temp is
  usually on the same drive as destination) but not impossible; the
  fallback must be tested.
- **12-hex MD5 collision** in libraries >16T files is academic, but the
  random 4-char suffix guarantees uniqueness on disk even if the
  theoretical collision occurs.
- **Scan-cache rebuild cost**: rebuilding the staging cache on every run
  is O(N) — same as today's scan-cache write. Acceptable for N<1M.
- **`history` schema migration** must be additive (no DROP/RECREATE)
  because the conversion DB persists across CLI invocations.