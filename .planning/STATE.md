# Planning State

## Active Phase
- **md5sum-staging** — redesign temp staging for UTF-8 safety + MAX_PATH handling

## Phase Context
- `.planning/md5sum-staging-CONTEXT.md` — decisions ready for research/planning

## Recent Changes (from git status)
- `src/app/pipeline/execute.py` — modified (sink wiring work)
- `tests/test_run_from_index_sink.py` — modified (test for sink wiring)

## What's Working Today
- Rich progress bar threading from `run_from_index` through prefilter → execute
- Phased execution: skip → copy → convert batches
- Long-path staging via `_short_hash` + `_path_is_long` in `long_path.py`
- Scan-cache (per-run, input-signature-keyed) for directory scan results
- Conversion history DB with `UNIQUE(source_path, dest_path)`

## Known Issues / Motivation
- qaac / CoreConverter UTF-8 path handling: non-ASCII names trigger 0-byte output
- Current staging only fires for >240-char paths; UTF-8 filenames with short paths
  go unstaged and fail
- Current temp filename is `<8-char-md5>__<basename>` — 8 hex chars is narrow
  for very large libraries; no collision recovery

## Deferred Ideas
- Source-file content hashing (own phase)
- Parallel/staged verification (own phase)
- Wine backend UTF-8 staging parity (own phase)
- CoreConverter retry on qaac-pipe failure (own phase)