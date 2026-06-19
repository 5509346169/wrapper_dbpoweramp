# Implementation Roadmap

Phases are ordered by dependency, not by "importance" — each phase should be independently
testable before moving to the next. Treat this as the backbone for `04-cursor-agent-tasks.md`.

## Phase 0 — Scaffolding
**Deliverables:** full directory tree from `00-overview-and-architecture.md` §4 (empty `__init__.py`
files where needed), `requirements.txt`, placeholder `settings.yaml`/`presets.yaml` (the examples
from `01-config-schema.md`), `README.md` with quickstart.
**Exit criteria:** `python main.py --help` runs (even if it does nothing yet) with no import errors.

## Phase 1 — Models & Config Loading
**Files:** `models/types.py`, `config/settings_loader.py`, `config/preset_loader.py`.
**Exit criteria:**
- Loading the example `settings.yaml`/`presets.yaml` produces correctly-typed dataclasses.
- A deliberately broken YAML (missing `ext`, bad backend name, etc.) raises a clear `ConfigError`/
  `PresetNotFoundError`, not a raw traceback.

## Phase 2 — Audio Inspector
**Files:** `audio/inspector.py`.
**Exit criteria:**
- Generate test fixtures with `ffmpeg` (a 1-second FLAC, a 1-second MP3, a 1-second ALAC-in-.m4a,
  a 1-second AAC-in-.m4a) and confirm `is_lossy()` correctly distinguishes the ALAC vs AAC pair —
  this is the single most important correctness test in the whole project, since it's the one
  extension-based assumption that *cannot* be allowed to leak in anywhere else.
- A corrupt/non-audio file raises `ProbeError` cleanly.

## Phase 3 — Path Resolver & Sidecar Manager
**Files:** `pathing/resolver.py`, `sidecars/manager.py`.
**Exit criteria:**
- `compute_output_path` unit tests covering: no `source_path`, `source_path` given with `--input`
  pointed at a nested subfolder, `--input` as a single file.
- `hide_filename` covers already-hidden names (no double dot).
- `copy_covers` with `hide: true` produces `.cover.jpg` in the output dir; with `hide: false`
  produces `cover.jpg`; re-running doesn't duplicate or error.
- `to_wine_path` is testable only if Wine is installed locally — gate this test, don't fail CI/dev
  runs without Wine; the function itself must still raise a clean `BackendError` if `winepath` is
  absent.

## Phase 4 — Backends
**Files:** `backends/base.py`, `backends/native_ffmpeg.py`, `backends/wine_dbpoweramp.py`,
`backends/registry.py`.
**Order:** build `native_ffmpeg` first — it's testable on any CachyOS box with `ffmpeg` installed,
no Wine setup required. Build `wine_dbpoweramp` second, and treat its tests as conditionally
skipped if Wine/dBpoweramp aren't present on the dev machine (don't block the rest of the project
on having a working Wine+dBpoweramp install).
**Exit criteria:**
- `native_ffmpeg.run()` actually transcodes a real test file end-to-end for at least 3 presets
  (`flac-lossless`, `mp3-320-cbr`, `opus-128`) and the output is a valid audio file per `ffprobe`.
- `requires_encoder` gating works: temporarily set `requires_encoder: "nonexistent_codec"` on a
  test preset and confirm a clean failure message instead of an ffmpeg crash dump.
- `registry.get_backend` raises immediately (before any file discovery) if the selected backend's
  environment is invalid.

## Phase 5 — Job Builder
**Files:** `jobs/builder.py`.
**Exit criteria:**
- Given a small synthetic folder tree (mix of lossy/lossless files, a `cover.jpg`, an `.lrc`),
  `build_jobs` with each of `LossyAction.LEAVE/COPY/CONVERT` produces the expected `job_type` per
  file.
- `--no-lossy-check` path skips probing entirely (verify via a probe-call counter/mock — probing
  should be **zero** calls in this mode, not "probe but ignore result").

## Phase 6 — History DB
**Files:** `history/db.py`.
**Exit criteria:**
- Resume behavior matches the original script (same source+dest+command+SUCCESS+file-exists →
  skip).
- New `job_type` mismatch (logged as `copy`, now requested as `convert`) does **not** skip.

## Phase 7 — Execution Runner
**Files:** `execution/runner.py`.
**Exit criteria:**
- End-to-end run on a small real test library (5–10 files, both backends if available) produces
  correct output tree, correct sidecar placement (including hidden covers), correct history DB
  rows, and correct final Success/Skipped/Failed counts.
- Re-running the identical command is fully skip-only (no reconversion) unless `--force`.

## Phase 8 — UI
**Files:** `ui/progress_view.py`.
**Exit criteria:** Visual smoke test — `-v` flag shows the live two-panel layout (progress +
verbose stream) exactly as in the original script, just sourced from the extracted class.

## Phase 9 — CLI & Orchestration
**Files:** `cli/args.py`, `main.py`.
**Exit criteria:**
- All cross-flag validation rules from `01-config-schema.md` §3 produce the documented errors.
- The **lossy gate** is provably hit: running against a folder containing a known-lossy file
  without `--lossy-action` exits non-zero with the file list printed, and crucially **does not**
  create any output files or history rows for that run.
- `--dry-run` and `--list-lossy` never touch the filesystem beyond reading/probing.

## Phase 10 — Documentation & Hardening
- `README.md`: install steps (CachyOS packages: `ffmpeg`, `wine` (AUR or repo), Python deps),
  example commands for both backends, example `--source-path` usage.
- Inline docstrings on every public function listed in `02-module-specifications.md`.
- A final pass checking **no module uses `shell=True`** anywhere (grep for it as a literal CI/lint
  step if you want to enforce this permanently).

## Suggested dependency graph (for parallelizing agent work if desired)

```
Phase 0
  └─▶ Phase 1 ──┬─▶ Phase 2 ──┐
                 ├─▶ Phase 3 ──┤
                 └─▶ Phase 4 ──┴─▶ Phase 5 ─▶ Phase 6 ─▶ Phase 7 ─▶ Phase 9
                                                  Phase 8 ──────────▲
                                                                 Phase 10 (last)
```
Phases 2, 3, 4 have no dependency on each other and can be built in any order (or in parallel
Cursor sessions) once Phase 1 is done.
