# Cursor Agent Task Backlog

## How to use this with Cursor

1. Put all five plan files (`00`–`04`) in the repo root under a `plans/` folder before opening the
   project in Cursor — that way `@plans/00-overview-and-architecture.md` etc. are referenceable
   from any agent chat.
2. Create an `AGENTS.md` at the repo root (template at the bottom of this file) so the constraints
   below persist across every Cursor Agent/Composer session automatically, not just the one where
   you pasted this task list.
3. Work through tasks **in order, one at a time**, in Cursor's Agent mode. After each task:
   - Let the agent finish and report.
   - Run the listed verification command(s) yourself (or have the agent run them).
   - Commit before starting the next task. Small commits make it trivial to roll back a task that
     went sideways without losing the whole session.
4. If a task fails verification, paste the failing output back into the same Cursor session and
   ask it to fix it — don't move to the next task with a known-broken one underneath it.

---

## `AGENTS.md` template (paste at repo root)

```markdown
# Agent Operating Rules — dBpoweramp Wrapper

- This project is intentionally NOT a pip package. Never add setup.py, pyproject.toml, or a
  console_scripts entry point. Run everything via `python main.py ...` from the repo root.
- Never use `subprocess` with `shell=True`. Always pass argument lists.
- Never infer audio losslessness from file extension. Always use `audio/inspector.py`'s
  ffprobe-based codec_name check.
- The lossy-action CLI flag has NO default value. Do not add one, even for convenience. If lossy
  files are found and the flag is missing, the run must abort with a clear message — see
  plans/01-config-schema.md §3.
- Every public function gets a docstring and type hints.
- Reference plans/00 through plans/04 before implementing anything in their scope — they are the
  source of truth for schemas and interfaces, not this file.
- After implementing a module, write or update a quick manual test/usage snippet showing it works,
  even if there's no formal test framework wired up yet.
```

---

## Task 1 — Scaffolding
**Goal:** Create the full directory/file skeleton.
**Reference:** `plans/00-overview-and-architecture.md` §4.
**Do:**
- Create every directory and `__init__.py` listed.
- Create `requirements.txt` with: `pyyaml`, `rich`. (No `ffmpeg-python`/Wine bindings needed —
  both backends shell out to real binaries.)
- Create `settings.yaml` and `presets.yaml` using the examples in
  `plans/01-config-schema.md` §1–§2 verbatim as a starting point.
- Create a minimal `README.md` (can be filled out properly in Task 13).
**Verify:** `python main.py --help` runs without `ImportError`/`ModuleNotFoundError` (a stub
`main.py` with just `import` statements + `if __name__ == "__main__": pass` is fine for now).

## Task 2 — Models
**Goal:** Implement `models/types.py` exactly per `plans/02-module-specifications.md`.
**Verify:** `python -c "from models.types import PresetConfig, ConversionJob, LossyAction; print('ok')"`.

## Task 3 — Config Loaders
**Goal:** Implement `config/settings_loader.py`, `config/preset_loader.py`, and a
`ConfigError`/`PresetNotFoundError` exceptions module (`exceptions.py` at repo root is fine).
**Verify:**
- Loading the real `settings.yaml`/`presets.yaml` succeeds and produces correctly-typed objects.
- Temporarily corrupt a copy of `presets.yaml` (delete an `ext` field) and confirm a clean
  `ConfigError`, not a raw `KeyError`.

## Task 4 — Audio Inspector
**Goal:** Implement `audio/inspector.py`.
**Setup the agent needs to do first:** generate 4 tiny test fixtures with ffmpeg into a
`tests/fixtures/` folder:
```
ffmpeg -f lavfi -i sine=duration=1 tests/fixtures/lossless.flac
ffmpeg -f lavfi -i sine=duration=1 -c:a alac tests/fixtures/alac.m4a
ffmpeg -f lavfi -i sine=duration=1 -c:a aac tests/fixtures/aac.m4a
ffmpeg -f lavfi -i sine=duration=1 -c:a libmp3lame tests/fixtures/lossy.mp3
```
**Verify:** a quick script asserting `is_lossy(alac.m4a) is False` and `is_lossy(aac.m4a) is True`
— this is the critical test, both files share the `.m4a` extension and must be told apart purely
by `codec_name`.

## Task 5 — Path Resolver & Sidecar Manager
**Goal:** Implement `pathing/resolver.py` and `sidecars/manager.py`.
**Verify:**
- `compute_output_path` against 3 scenarios from `plans/03-implementation-roadmap.md` Phase 3.
- Build a fake `tests/fixtures/album/` with `track.flac` + `cover.jpg` + `lyrics.lrc`, run
  `copy_covers`/`copy_lyrics` with `hide=True` for covers, confirm output has `.cover.jpg` and a
  plain `lyrics.lrc`.

## Task 6 — Backend Base + Native ffmpeg Backend
**Goal:** Implement `backends/base.py` and `backends/native_ffmpeg.py`.
**Verify:** Using the `flac-lossless`, `mp3-320-cbr`, and `opus-128` presets, actually transcode
`tests/fixtures/lossless.flac` end-to-end and confirm with `ffprobe` that the output codec matches
expectations.

## Task 7 — Wine dBpoweramp Backend
**Goal:** Implement `backends/wine_dbpoweramp.py`.
**Note for the agent:** if Wine + dBpoweramp aren't installed in this dev environment, implement
against the spec and write the test as a `pytest.mark.skipif`-style guard (or equivalent manual
check) rather than failing the task — this backend's runtime correctness can only be confirmed on
a machine with the actual Wine prefix set up.
**Verify (when Wine is available):** `validate_environment()` passes; a real conversion through
`CoreConverter.exe` via Wine succeeds for at least one preset.
**Verify (always, regardless of Wine availability):** `validate_environment()` raises a clear
`BackendError` when `wine_binary`/`winepath_binary` don't resolve — point `settings.yaml` at a
nonexistent binary name temporarily to confirm.

## Task 8 — Backend Registry
**Goal:** Implement `backends/registry.py`.
**Verify:** `resolve_backend_for_run(None, settings)` returns the settings default;
`resolve_backend_for_run(Backend.NATIVE_FFMPEG, settings)` overrides it; `get_backend` for an
unconfigured/broken backend raises before returning, not on first use.

## Task 9 — Job Builder
**Goal:** Implement `jobs/builder.py`.
**Verify:** Build a small mixed test tree (lossless + lossy + a file with no cover) and confirm,
for each `LossyAction` value, the `job_type` assigned to the lossy file matches
`plans/02-module-specifications.md`'s `build_jobs` table. Confirm `--no-lossy-check` equivalent
call makes **zero** ffprobe invocations (instrument/mock the probe function to count calls).

## Task 10 — History DB
**Goal:** Implement `history/db.py` as a refactor of the original script's `ConversionDB`, plus
the new `job_type` column.
**Verify:** Log a `convert` job as SUCCESS, confirm a second identical run's resume check skips
it; change only `job_type` to `copy` for the same source/dest and confirm it does **not** skip.

## Task 11 — Execution Runner
**Goal:** Implement `execution/runner.py`, wiring backend + history + sidecars together.
**Verify:** Full run over `tests/fixtures/album/` with the `flac-lossless` preset and
`--lossy-action convert`: correct output files, correct hidden cover, correct DB rows, correct
summary counts. Re-run identically — everything reports `SKIPPED` except with `--force`.

## Task 12 — UI
**Goal:** Implement `ui/progress_view.py`, extracting the original script's `rich` wiring into a
class with `start()`/`update_log()`/`stop()`.
**Verify:** Manual visual check with `-v` on a multi-file run — two-panel layout (progress bar +
live verbose stream) renders as it did in the original script.

## Task 13 — CLI & main.py Orchestration
**Goal:** Implement `cli/args.py` and finish `main.py` per the orchestration steps in
`plans/02-module-specifications.md`'s `main.py` section.
**Verify, all of these explicitly:**
1. `--source-path` that is NOT an ancestor of `--input` → clean error, no files touched.
2. A run against a folder with at least one lossy file, no `--lossy-action`, no `--dry-run`/
   `--list-lossy`/`--no-lossy-check` → exits non-zero, prints the offending files, **creates no
   output files and no history rows**.
3. Same run with `--lossy-action leave` → lossy file shows as `SKIPPED` in the summary, no output
   created for it, lossless files in the same folder still convert normally.
4. Same run with `--lossy-action copy` → lossy file appears unchanged in the output tree at its
   correct mirrored path, no transcoding occurred for it.
5. `--dry-run` and `--list-lossy` touch zero output files regardless of lossy content.
6. Full README pass: every documented CLI flag in `plans/01-config-schema.md` §3 actually exists
   in `argparse` and behaves as documented.

## Task 14 — Documentation & Final Hardening
**Goal:** Finish `README.md` (CachyOS install notes for `ffmpeg`/`wine`, both backend setup paths,
example commands), confirm no `shell=True` anywhere (`grep -rn "shell=True" .` should return
nothing), confirm every public function listed across `plans/02-module-specifications.md` has a
docstring.
**Verify:** Fresh read-through of `README.md` by literally following it on a clean checkout —
every command in it should work as written.
