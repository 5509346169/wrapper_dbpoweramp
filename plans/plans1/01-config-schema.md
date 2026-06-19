# Config Schema — `settings.yaml` and `presets.yaml`

Both files are YAML, loaded once at startup and validated before any file discovery begins
(fail fast on bad config, never partway through a run).

## 1. `settings.yaml` — environment / backend / execution config

```yaml
backend:
  default: "native_ffmpeg"        # "wine_dbpoweramp" | "native_ffmpeg" — used if --backend not passed

  wine_dbpoweramp:
    wine_binary: "wine"
    wine_prefix: "~/.wine-dbpoweramp"          # WINEPREFIX env var value
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
    winepath_binary: "winepath"

  native_ffmpeg:
    ffmpeg_binary: "ffmpeg"
    flac_binary: "flac"            # used only if a preset prefers the standalone flac CLI
    lame_binary: "lame"            # used only if a preset prefers the standalone lame CLI
    opusenc_binary: "opusenc"      # used only if a preset prefers the standalone opusenc CLI

tools:
  ffprobe_binary: "ffprobe"        # always native, regardless of conversion backend

history:
  db_path: "conversion_history.db"

execution:
  default_workers: 4               # conversion pool size
  probe_workers: 8                 # ffprobe pre-flight pool size (I/O bound, can be higher)
  worker_model: "thread"           # "thread" | "process"

logging:
  level: "INFO"                    # DEBUG | INFO | WARNING | ERROR
```

### Validation rules

- `backend.default` must be one of the two literal backend names.
- If `wine_dbpoweramp` is selected (by default or `--backend`), `wine_binary`, `wine_prefix`,
  `coreconverter_path`, and `winepath_binary` must all resolve (binaries on `$PATH` or absolute
  paths that exist; `wine_prefix` directory must exist).
- `tools.ffprobe_binary` must resolve regardless of backend — lossy detection always runs.
- `execution.default_workers` and `probe_workers` must be positive integers.

## 2. `presets.yaml` — encoding presets

Each preset now declares **per-backend** encoder identity/args (a preset may support only one
backend — that's valid, it just can't be run with `--backend` set to the unsupported one), plus
sidecar/cover policy.

```yaml
presets:
  flac-lossless:
    ext: ".flac"
    backends:
      wine_dbpoweramp:
        encoder: "FLAC"
        args: ["-compression-level-5", "-verify"]
      native_ffmpeg:
        tool: "ffmpeg"                       # or "flac" to use the standalone CLI instead
        args: ["-c:a", "flac", "-compression_level", "5"]
    sidecars:
      lyrics:
        copy: true
        extensions: [".lrc", ".txt"]
        hide: false
      covers:
        copy: true
        patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"]
        hide: true                            # → copied as ".cover.jpg" etc.

  mp3-v0-vbr:
    ext: ".mp3"
    backends:
      wine_dbpoweramp:
        encoder: "mp3 (LAME)"
        args: ["-V 0", "-encoding=\"SLOW\""]
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libmp3lame", "-q:a", "0"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }

  mp3-320-cbr:
    ext: ".mp3"
    backends:
      wine_dbpoweramp:
        encoder: "mp3 (LAME)"
        args: ["-b 320"]
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libmp3lame", "-b:a", "320k"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }

  aac-vbr-high:
    ext: ".m4a"
    backends:
      wine_dbpoweramp:
        encoder: "m4a FDK (AAC)"
        args: ["-m 5"]
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libfdk_aac", "-vbr", "5"]   # requires ffmpeg build with libfdk_aac
        requires_encoder: "libfdk_aac"               # checked via `ffmpeg -encoders` before running
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }

  qaac-cvbr-256:
    ext: ".m4a"
    backends:
      wine_dbpoweramp:
        encoder: "m4a QAAC (iTunes)"
        args: ["-cbr_vbr=\"cVBR\"", "-bitrate=\"256\"", "-codec=\"LC AAC\"", "-keepsr"]
        # NOTE: no native_ffmpeg block — this preset is Wine-only by design (see overview doc §6)
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }

  opus-128:
    ext: ".opus"
    backends:
      wine_dbpoweramp:
        encoder: "Opus"
        args: ["-bitrate 128"]
      native_ffmpeg:
        tool: "ffmpeg"
        args: ["-c:a", "libopus", "-b:a", "128k"]
    sidecars:
      lyrics: { copy: true, extensions: [".lrc", ".txt"], hide: false }
      covers: { copy: true, patterns: ["cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"], hide: true }
```

### Validation rules

- `ext` required, must start with `.`.
- At least one of `backends.wine_dbpoweramp` / `backends.native_ffmpeg` required.
- If `--backend X` is passed and the chosen preset has no `backends.X` block →
  hard error: `Preset 'qaac-cvbr-256' has no native_ffmpeg configuration. Available backends for this preset: wine_dbpoweramp`.
- `sidecars.lyrics` / `sidecars.covers` are both optional blocks; omitted = no sidecar handling of
  that kind for this preset. `hide` defaults to `false` if omitted.
- `requires_encoder` (native_ffmpeg only, optional) — if present, the backend checks
  `ffmpeg -encoders` output before running and fails fast with an actionable message instead of
  letting ffmpeg fail mid-batch.

## 3. CLI flags (full surface for `main.py`)

| Flag | Required | Notes |
|---|---|---|
| `-I, --input` | yes | File or directory to convert |
| `-O, --output` | yes | Output root directory |
| `--source-path` | no | Root used for relative-path math instead of `--input`; `--input` must be inside it |
| `-p, --preset` | yes | Key from `presets.yaml` |
| `--backend` | no | `wine_dbpoweramp` \| `native_ffmpeg`; overrides `settings.yaml` default |
| `--lossy-action` | conditional | `leave` \| `copy` \| `convert`; **required if any lossy source files are found**, otherwise unused |
| `--no-lossy-check` | no | Explicitly disables ffprobe lossy detection entirely (still must be passed deliberately — this itself is the "explicit" escape hatch, not a default) |
| `-w, --workers` | no | Overrides `execution.default_workers` |
| `--worker-model` | no | `thread` \| `process`, overrides settings |
| `-v, --verbose` | no | Live conversion stream panel |
| `--exclude` | no, repeatable | Folder names to skip |
| `--db` | no | Overrides `history.db_path` |
| `--force` | no | Ignore resume history, reconvert everything |
| `--dry-run` | no | Build and print the job list (incl. lossy classification) without converting anything |
| `--list-lossy` | no | Shorthand: scan + print lossy files found, then exit (no `--lossy-action` needed) |

### Cross-flag validation (enforced in `cli/args.py`, before job building starts)

1. `--source-path` given → must be an ancestor directory of `--input` (or of `--input`'s parent if
   `--input` is a file). Otherwise: hard error.
2. `--lossy-action` given but `--no-lossy-check` also given → hard error (contradictory).
3. `--dry-run` and `--list-lossy` are mutually exclusive with actually requiring `--lossy-action` —
   both are inspection-only modes that never need it.
4. If neither `--dry-run`, `--list-lossy`, nor `--no-lossy-check` is given, and the Job Builder's
   pre-flight probe finds ≥1 lossy source file, and `--lossy-action` was not given →
   **abort before any conversion starts**, printing the count and a sample of offending file paths,
   and the exact flag the user needs to add.
