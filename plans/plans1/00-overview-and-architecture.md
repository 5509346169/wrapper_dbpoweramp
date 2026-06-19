# dBpoweramp Wrapper — Architecture Overview

## 0. Why this is a rewrite, not a port

The supplied `dbpoweramp_cli4.py` is built around `C:\Program Files\dBpoweramp\CoreConverter.exe` —
a Windows-only binary. dBpoweramp has no native Linux build. On CachyOS, the only way to call the
*real* dBpoweramp encoders (LAME, FDK AAC, QAAC, dBpoweramp's own FLAC implementation, etc.) is
through **Wine**. That single fact drives most of the architecture below.

Per your decision, the wrapper ships **two pluggable backends** instead of committing to one:

| Backend | What it runs | When you'd use it |
|---|---|---|
| `wine_dbpoweramp` | The real `CoreConverter.exe` inside a Wine prefix | You want byte-identical output to your existing dBpoweramp presets (QAAC, FDK AAC, dBpoweramp's FLAC/verify pass) |
| `native_ffmpeg` | `ffmpeg`/`flac`/`opusenc`/`lame` installed natively on CachyOS | You want zero Wine dependency, faster startup, simpler debugging |

Backend selection is **per-run** (`--backend`) with a fallback to **per-preset** declared support,
falling back again to a global default in `settings.yaml`. A preset that only declares one backend's
args will refuse to run on the other backend with a clear error — it will not silently fall back to
"close enough" args.

## 1. Non-goals

- This is **not** a pip-installable package. No `setup.py`, no `pyproject.toml`, no `__init__.py`
  turning the tree into a distributable. It's a flat, modular *script project* you run with
  `python main.py ...` directly from the repo. (Folders are used purely for organization — Python
  still needs `__init__.py` marker files for the `import` statements to resolve packages within the
  project, but that's a language requirement, not a packaging/distribution choice.)
- No GUI. CLI + `rich` live progress only (carried over from the existing script).
- No attempt to reimplement dBpoweramp's DSP — `wine_dbpoweramp` is a thin bridge, not a reverse
  engineering effort.

## 2. Design principles

1. **Explicit over implicit.** Per your second decision: when a lossy source file is detected, there
   is **no default action**. The run aborts before any conversion starts if lossy files exist and
   `--lossy-action` wasn't passed, printing exactly which files triggered it and the flag options.
2. **Codec truth comes from `ffprobe`, never from file extension.** `.m4a` can be AAC (lossy) or ALAC
   (lossless); `.wav` is almost always PCM but can wrap lossy codecs in rare cases. Every file is
   probed for `codec_name` and checked against a lossless-codec allowlist.
3. **Backends are interchangeable at the call-site.** Everything above the backend layer (job
   building, sidecar handling, history, UI) is backend-agnostic. It calls
   `backend.run(infile, outfile, preset)` and gets back a uniform `JobResult`.
4. **Resumability is preserved and extended.** The SQLite history table from the original script is
   kept, with an added `job_type` column (`convert` / `copy`) so re-runs don't reconvert a file that
   was deliberately copied-as-is under a lossy policy.
5. **No `shell=True`.** The original script built a single shell string and passed `shell=True` to
   `subprocess.Popen`, which is fragile with filenames containing spaces/quotes/special characters
   and is an unnecessary injection surface. The rewrite builds argument lists and calls
   `subprocess.Popen(args, shell=False, ...)` for both backends (Wine invocation included).
6. **Idempotent sidecar copying.** Cover/lyric files are only copied if the destination doesn't
   already exist, exactly like the original — kept as-is, just generalized into config.

## 3. High-level data flow

```
 ┌──────────────┐     ┌────────────────┐     ┌───────────────────┐
 │  CLI args     │────▶│  Job Builder    │────▶│ Lossy gate check   │
 │ (--input,     │     │ (walk tree,     │     │ (abort if needed   │
 │  --source-path,     │  ffprobe each   │     │  flag missing)     │
 │  --preset,    │     │  audio file)    │     └─────────┬──────────┘
 │  --backend,   │     └────────────────┘               │
 │  --lossy-action)                                       ▼
 └──────────────┘                                ┌─────────────────┐
                                                   │ ConversionJob[]  │
                                                   │ (convert/copy/   │
                                                   │  skip per file)  │
                                                   └────────┬─────────┘
                                                            ▼
                                          ┌──────────────────────────────┐
                                          │ Execution Runner (thread pool)│
                                          │  per job:                     │
                                          │   1. History DB resume check  │
                                          │   2. Backend.run() or copy2() │
                                          │   3. Sidecar Manager           │
                                          │   4. History DB log            │
                                          │   5. Progress UI update        │
                                          └──────────────────────────────┘
```

## 4. Directory layout

```
dbpamp-wrapper/
├── main.py                     # entrypoint: parse args, wire modules, run
├── settings.yaml               # backend config, tool paths, execution defaults
├── presets.yaml                # encoding presets (per-backend args + sidecar policy)
├── requirements.txt
├── README.md
├── config/
│   ├── __init__.py
│   ├── settings_loader.py
│   └── preset_loader.py
├── models/
│   ├── __init__.py
│   └── types.py                # dataclasses + enums shared across modules
├── audio/
│   ├── __init__.py
│   └── inspector.py            # ffprobe wrapper, lossy/lossless classification
├── pathing/
│   ├── __init__.py
│   └── resolver.py             # source-path math, wine path translation, dotfile hide
├── sidecars/
│   ├── __init__.py
│   └── manager.py              # lyric/cover copy + hidden-cover renaming
├── backends/
│   ├── __init__.py
│   ├── base.py                 # ConversionBackend ABC
│   ├── native_ffmpeg.py
│   ├── wine_dbpoweramp.py
│   └── registry.py             # backend selection logic
├── jobs/
│   ├── __init__.py
│   └── builder.py              # discover files, classify, build ConversionJob list
├── history/
│   ├── __init__.py
│   └── db.py                   # sqlite resume/log (refactor of ConversionDB)
├── execution/
│   ├── __init__.py
│   └── runner.py                # ThreadPoolExecutor orchestration
├── ui/
│   ├── __init__.py
│   └── progress_view.py         # rich Live/Panel/Progress wrapper
└── cli/
    ├── __init__.py
    └── args.py                  # argparse definition + cross-flag validation
```

## 5. Key decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Backend strategy | Pluggable (`wine_dbpoweramp` + `native_ffmpeg`) | You chose future-proof over committing to one path; lets you A/B output quality later |
| Lossy-action default | None — hard stop if undecided | You explicitly rejected a silent default; protects against accidentally re-encoding lossy sources at scale |
| Codec detection | `ffprobe codec_name`, not extension | Only reliable way to catch ALAC-in-.m4a vs AAC-in-.m4a, etc. |
| Packaging | No `setup.py`/`pyproject.toml` | Explicit user requirement — flat modular scripts only |
| Hidden cover files | Per-preset `covers.hide: true/false`, dot-prefix on copy | User requirement — opt-in per preset, not global |
| Folder rebuild | `--source-path` separate from `--input` | Lets you convert a single album while output mirrors the full library tree |
| Shell invocation | Arg-list `Popen`, no `shell=True` | Correctness/safety fix over the original script |

## 6. Known risks / limitations (flag these to the Cursor agent, don't silently "fix" them away)

- **QAAC under Wine is fragile.** It depends on Apple's `CoreAudioToolbox.dll`, normally sourced from
  an iTunes install inside the same Wine prefix. If that's not present, `wine_dbpoweramp` will fail
  loudly for the `qaac-cvbr-256` preset specifically — this is expected, not a bug to "work around"
  silently.
- **`libfdk_aac` licensing.** Distro `ffmpeg` builds (including CachyOS's repo package) often omit
  `libfdk_aac` for licensing reasons. The `native_ffmpeg` backend's AAC preset should detect this via
  `ffmpeg -encoders` and fail with a clear message rather than silently substituting the native `aac`
  encoder and calling it equivalent.
- **`winepath` dependency.** Path translation for `wine_dbpoweramp` requires the `winepath` utility
  (ships with `wine`). Validate its presence at startup when that backend is selected.
- **Double-probing cost.** ffprobe is invoked once per audio file for lossy classification. For very
  large libraries this is the dominant pre-flight cost — the Job Builder should support
  `--workers` for the probe pass too, not just the conversion pass (see module spec).
