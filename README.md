# dBpoweramp Wrapper

A CLI tool that wraps **dBpoweramp CoreConverter.exe** (via Wine) and **native FFmpeg** for
cross-platform audio format conversion on Linux. The dBpoweramp rewrite targets CachyOS Linux
specifically — it calls the real dBpoweramp encoders through Wine, and also ships a fully native
FFmpeg path for users who want zero Wine dependency.

See `plans/` for design documents and `01-config-schema.md` for the full preset/backend schema.

---

## Installation

### Packages

Install audio tools from the official CachyOS repos:

```sh
sudo pacman -S ffmpeg wine python-pyyaml python-rich
```

- `ffmpeg` — provides `ffmpeg` and `ffprobe`. For the `aac-vbr-high` native preset with FDK AAC,
  the standard repo `ffmpeg` may omit `libfdk_aac`; use `ffmpeg-full` from the AUR if needed.
- `wine` — provides `wine`, `winepath`, and the Wine runtime. **No `wine-mono` or `wine-gecko`
  is needed** — this wrapper calls CoreConverter.exe as a CLI tool only, not as a .NET/WinForms app.
- `python-pyyaml` and `python-rich` — Python dependencies.

### Python dependencies

```sh
pip install -r requirements.txt
# or, with uv:
uv sync
```

`requirements.txt` and `pyproject.toml` both declare only `pyyaml` and `rich`.

### Wine prefix setup (for `wine_dbpoweramp` backend)

If you plan to use the `wine_dbpoweramp` backend, create a dedicated Wine prefix and install
dBpoweramp inside it:

```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
```

Then run the dBpoweramp installer inside the prefix:

```sh
WINEPREFIX=~/.wine-dbpoweramp wine /path/to/dBpowerampReference食用.exe
```

Note: the `qaac-cvbr-256` preset requires Apple's `CoreAudioToolbox.dll` from an iTunes install
inside the same prefix. This is a known fragility — if the DLL is absent, the preset fails
with a clear error from QAAC itself. This is not a bug in the wrapper.

---

## Quick start

### Native FFmpeg (default backend)

```sh
python main.py -I ~/Music -O ~/Converted -p flac-lossless
```

### Wine dBpoweramp backend

```sh
python main.py -I ~/Music -O ~/Converted -p qaac-cvbr-256 --backend wine_dbpoweramp
```

### Other common presets

```sh
# MP3 V0 via native ffmpeg
python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr

# Opus 128 via Wine dBpoweramp
python main.py -I ~/Music -O ~/Converted -p opus-128 --backend wine_dbpoweramp

# AAC VBR via native ffmpeg (requires libfdk_aac in ffmpeg)
python main.py -I ~/Music -O ~/Converted -p aac-vbr-high
```

### Path math with `--source-path`

Convert a single sub-folder while preserving the full library tree in the output:

```sh
python main.py -I ~/Music/Artist/Album -O ~/Converted \
    --source-path ~/Music \
    -p flac-lossless
```

Output lands at `~/Converted/Artist/Album/` instead of directly in `~/Converted/`.

---

## Available presets

| Preset | Output | Backends |
|--------|--------|----------|
| `flac-lossless` | FLAC (compression level 5) | native_ffmpeg, wine_dbpoweramp |
| `mp3-v0-vbr` | MP3 V0 | native_ffmpeg, wine_dbpoweramp |
| `mp3-320-cbr` | MP3 320 kbps | native_ffmpeg, wine_dbpoweramp |
| `aac-vbr-high` | AAC VBR high quality | native_ffmpeg, wine_dbpoweramp |
| `qaac-cvbr-256` | AAC 256 kbps via QAAC | wine_dbpoweramp only |
| `opus-128` | Opus 128 kbps | native_ffmpeg, wine_dbpoweramp |

`native_ffmpeg` is the default backend (set in `settings.yaml`). Override with `--backend`.

---

## CLI flags

| Flag | Required | Description |
|------|----------|-------------|
| `-I, --input PATH` | yes | File or directory to convert |
| `-O, --output PATH` | yes | Output root directory |
| `-p, --preset NAME` | yes | Preset name from `presets.yaml` (e.g. `flac-lossless`, `mp3-320-cbr`) |
| `--source-path PATH` | no | Root for relative-path math; `--input` must be inside it |
| `--backend NAME` | no | `wine_dbpoweramp` or `native_ffmpeg`; overrides `settings.yaml` default |
| `--lossy-action ACTION` | conditional | `leave` (skip), `copy` (pass through), `convert` (transcode). **Required if any lossy source files are found.** |
| `--no-lossy-check` | no | Disable ffprobe lossy detection entirely |
| `-w, --workers N` | no | Override thread/process pool size (default from `settings.yaml`) |
| `--worker-model MODEL` | no | `thread` or `process`; overrides `settings.yaml` |
| `-v, --verbose` | no | Live verbose conversion stream |
| `--exclude DIR` | no | Folder names to skip; can be repeated |
| `--db PATH` | no | Override history database path |
| `--force` | no | Ignore resume history, reconvert everything |
| `--dry-run` | no | Build and print job list without converting |
| `--list-lossy` | no | Scan and print lossy files, then exit |

---

## Lossy source files

The lossy-action gate is a hard error. If any lossy source files are detected (verified by
`ffprobe` codec detection — not by file extension) and `--lossy-action` is not given, the run
aborts immediately before touching the output directory or history database, printing the
offending file paths and the exact flag needed to proceed.

- `--lossy-action leave` — skip lossy files entirely; they appear as `SKIPPED` in the summary.
- `--lossy-action copy` — copy lossy files as-is to the output tree (no transcoding).
- `--lossy-action convert` — transcode lossy sources to the target format.

`--no-lossy-check` disables the probe entirely; use it when you are certain the source is
all-lossless and want to skip the pre-flight scan on very large libraries.

`--list-lossy` scans and prints lossy files found, then exits — useful for deciding which
policy to use before running the full batch.

---

## Resume / history

Successful conversions are logged to `conversion_history.db` (SQLite). Re-running against the
same input/output paths skips already-completed conversions. Use `--force` to reconvert
everything. The history table tracks `job_type` (`convert` / `copy`) — a file previously
copied as-is under a `copy` policy is not skipped if you re-run with a `convert` policy.

---

## Sidecar files

Lyric and cover-art files are copied alongside converted audio files per the preset's
`sidecars` block in `presets.yaml`. When `hide: true` (the default for covers), the cover is
renamed to a dot-prefixed name (e.g. `cover.jpg` → `.cover.jpg`) so it is hidden in
standard file browsers.

---

## Known limitations

- **QAAC requires CoreAudioToolbox.dll.** The `qaac-cvbr-256` preset works only with the
  Wine dBpoweramp backend and depends on Apple's `CoreAudioToolbox.dll` from an iTunes install
  inside `~/.wine-dbpoweramp`. If absent, QAAC fails with a readable error — this is expected,
  not a wrapper bug.

- **libfdk_aac may be absent.** CachyOS's repo `ffmpeg` often omits `libfdk_aac`. If you use
  the `aac-vbr-high` native preset, the wrapper checks `ffmpeg -encoders` before running and
  fails with an actionable message. Install `ffmpeg-full` from the AUR or rebuild `ffmpeg` with
  FDK AAC enabled.

- **winepath dependency.** Path translation for `wine_dbpoweramp` requires the `winepath`
  utility, which ships with `wine`. The wrapper validates its presence at startup when that
  backend is selected.

- **Double-probing cost.** Each source file is probed once with `ffprobe` during the
  pre-flight lossy-classification scan. For large libraries this is the dominant pre-flight
  cost; the probe pass uses a thread pool but cannot be parallelized with the conversion pass.

---

## Design docs

- `plans/plans1/00-overview-and-architecture.md` — architecture overview, design principles, known risks
- `plans/plans1/01-config-schema.md` — settings.yaml and presets.yaml schema, full CLI flag table
- `plans/plans1/02-module-specifications.md` — per-module signatures and contracts
- `plans/plans1/03-implementation-roadmap.md` — phased implementation notes
- `plans/plans1/04-cursor-agent-tasks.md` — task list and AGENTS.md rules
