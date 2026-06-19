# Module Specifications

Each section = one file/module. Signatures are the *contract* the Cursor agent should implement
against; internal logic is left to the agent but must satisfy the edge cases listed.

---

## `models/types.py`

Pure dataclasses/enums, no I/O, no imports from other project modules (this is the dependency root).

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

class Backend(str, Enum):
    WINE_DBPOWERAMP = "wine_dbpoweramp"
    NATIVE_FFMPEG = "native_ffmpeg"

class LossyAction(str, Enum):
    LEAVE = "leave"
    COPY = "copy"
    CONVERT = "convert"

JobType = Literal["convert", "copy", "skip"]
JobStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]

@dataclass
class SidecarPolicy:
    copy: bool = False
    extensions: list[str] = field(default_factory=list)
    hide: bool = False

@dataclass
class CoverPolicy:
    copy: bool = False
    patterns: list[str] = field(default_factory=list)
    hide: bool = False

@dataclass
class BackendPresetArgs:
    encoder: Optional[str] = None        # wine_dbpoweramp identity, e.g. "FLAC"
    tool: Optional[str] = None           # native_ffmpeg tool, e.g. "ffmpeg" / "flac"
    args: list[str] = field(default_factory=list)
    requires_encoder: Optional[str] = None

@dataclass
class PresetConfig:
    name: str
    ext: str
    backends: dict[Backend, BackendPresetArgs]
    lyrics: Optional[SidecarPolicy] = None
    covers: Optional[CoverPolicy] = None

@dataclass
class ConversionJob:
    infile: Path
    outfile: Path
    preset: PresetConfig
    job_type: JobType
    is_lossy_source: Optional[bool]      # None = not probed (e.g. --no-lossy-check)
    reason: Optional[str] = None         # why job_type was chosen (for --dry-run output)

@dataclass
class JobResult:
    job: ConversionJob
    status: JobStatus
    error_msg: Optional[str] = None
    stdout: Optional[str] = None
```

---

## `config/settings_loader.py`

```python
def load_settings(path: Path) -> Settings: ...
```
- Parses `settings.yaml` into a `Settings` dataclass (mirror schema in `01-config-schema.md`).
- Raises `ConfigError` (custom exception) with a human-readable message on missing/invalid keys —
  never `KeyError`/`AttributeError` bubbling up raw.
- Resolves `~` in `wine_prefix` via `Path.expanduser()`.
- Does **not** verify binaries exist on disk — that's `backends/registry.py`'s job (this loader is
  pure parsing).

## `config/preset_loader.py`

```python
def load_presets(path: Path) -> dict[str, PresetConfig]: ...
def get_preset(presets: dict[str, PresetConfig], name: str) -> PresetConfig: ...
```
- Parses `presets.yaml`, builds `PresetConfig` per entry.
- `get_preset` raises `PresetNotFoundError` listing available preset names if `name` isn't found
  (mirrors the original script's friendly error, but as an exception type, not an early `return`).
- Validates: `ext` starts with `.`; at least one backend block present per preset.

---

## `audio/inspector.py`

```python
LOSSLESS_CODECS = {
    "flac", "alac", "ape", "wavpack", "tta", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "shorten",
}

def probe_codec(file: Path, ffprobe_binary: str) -> str:
    """Returns ffprobe's codec_name for the first audio stream. Raises ProbeError on failure."""

def is_lossy(file: Path, ffprobe_binary: str) -> bool:
    """True if codec_name not in LOSSLESS_CODECS. Never infers from file extension."""

def probe_many(files: list[Path], ffprobe_binary: str, workers: int) -> dict[Path, bool]:
    """Thread-pooled batch probe (I/O bound) — used for the pre-flight lossy-gate scan."""
```
- `ffprobe` invocation: `[ffprobe_binary, "-v", "error", "-select_streams", "a:0",
  "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", str(file)]`,
  `shell=False`.
- On a file with no audio stream / corrupt header → `ProbeError`, surfaced by the caller as a
  per-file `FAILED` job result, not a crash of the whole batch.
- `probe_many` must not re-probe a file already in an in-memory cache within the same run (a file
  could theoretically appear once; cache is mostly future-proofing for retry logic, keep it simple —
  a plain `dict` is sufficient, no need for persistence here).

---

## `pathing/resolver.py`

```python
def compute_output_path(infile: Path, input_root: Path, source_root: Path | None,
                         output_root: Path, target_ext: str) -> Path:
    """
    Mirrors the original script's rel_path logic, but relative-to source_root when given.
    - If source_root is None: behave exactly like the original (relative to input_root,
      or just the bare filename if input_root is a single file).
    - If source_root is given: rel_path = infile.relative_to(source_root); this lets
      `--input` point at a subfolder while output still reproduces the full library tree.
    """

def validate_source_path(input_path: Path, source_path: Path) -> None:
    """Raises PathConfigError if input_path is not source_path or inside it."""

def hide_filename(name: str) -> str:
    """'cover.jpg' -> '.cover.jpg'. No-op if name already starts with '.'."""

def to_wine_path(linux_path: Path, wine_binary: str, wine_prefix: str,
                  winepath_binary: str) -> str:
    """
    Shells out to `winepath -w <path>` with WINEPREFIX=wine_prefix set, returns the
    Windows-style path string Wine/CoreConverter expects. Raises BackendError if
    winepath is missing or exits non-zero.
    """
```
- `compute_output_path` is pure (no I/O) and unit-testable with plain `Path` objects — no temp
  files needed in tests.
- `validate_source_path` uses `Path.is_relative_to()` (3.9+); CachyOS ships current Python so this
  is safe to rely on.

---

## `sidecars/manager.py`

```python
def copy_lyrics(infile: Path, outfile: Path, policy: SidecarPolicy | None) -> list[Path]:
    """Copies matching lyric/text sidecars next to outfile. Returns list of files written."""

def copy_covers(infile: Path, outfile: Path, policy: CoverPolicy | None) -> list[Path]:
    """
    Looks for policy.patterns in infile.parent. For each match, copies to outfile.parent,
    applying hide_filename() if policy.hide is True. Skips if destination already exists
    (idempotent, same as original script).
    """
```
- Both functions are no-ops (return `[]`) if `policy is None` or `policy.copy is False`.
- Cover copy must only happen **once per output directory**, not once per track — many tracks in
  an album share the same `cover.jpg`. The "skip if destination exists" check already gives this
  for free; the Execution Runner should still avoid redundant copy *attempts* where cheap to do so,
  but correctness doesn't depend on it.

---

## `backends/base.py`

```python
class ConversionBackend(ABC):
    @abstractmethod
    def name(self) -> Backend: ...

    @abstractmethod
    def validate_environment(self) -> None:
        """Check binaries/paths/prefix exist. Raise BackendError with a fix-it message if not."""

    @abstractmethod
    def supports(self, preset: PresetConfig) -> bool:
        """True if preset.backends contains this backend's key."""

    @abstractmethod
    def run(self, job: ConversionJob, stream_callback: Callable[[str], None] | None) -> JobResult:
        """Execute the conversion. Must use shell=False. Must call stream_callback per output line
        when verbose streaming is enabled (mirrors original script's verbose_queue behavior)."""
```

## `backends/native_ffmpeg.py`
- Builds `[ffmpeg_binary, "-y", "-i", str(infile), *preset_args, str(outfile)]` (or calls the
  standalone `flac`/`lame`/`opusenc` binary instead if `BackendPresetArgs.tool` names it).
- Before running, if `requires_encoder` is set, runs `ffmpeg -encoders` once (cache the result for
  the whole process lifetime, not per-file) and checks the encoder name is listed; raises
  `BackendError` naming the missing encoder and a CachyOS-appropriate fix (e.g. "install
  `ffmpeg-full` from the AUR, or rebuild presets without `libfdk_aac`").
- `-y` (overwrite) is safe here because resume/skip logic already happened upstream in the
  Execution Runner before `backend.run()` is ever called.

## `backends/wine_dbpoweramp.py`
- `validate_environment()`: checks `wine_binary`, `winepath_binary` resolve via `shutil.which`
  (or are absolute existing paths), `wine_prefix` directory exists, and a quick
  `wine --version` call succeeds.
- `run()`: translates `infile`/`outfile` via `pathing.resolver.to_wine_path`, builds
  `[wine_binary, coreconverter_path, f'-infile={wine_infile}', f'-outfile={wine_outfile}',
  f'-convert_to={encoder}', *args]` with `env={"WINEPREFIX": wine_prefix, ...os.environ}`,
  `shell=False`.
- Streams stdout line-by-line exactly like the original script's `run_conversion_stream`, just
  without `shell=True`.

## `backends/registry.py`

```python
def get_backend(name: Backend, settings: Settings) -> ConversionBackend: ...
def resolve_backend_for_run(cli_backend: Backend | None, settings: Settings) -> Backend:
    """cli_backend if given, else settings.backend.default."""
```
- `get_backend` instantiates and immediately calls `validate_environment()` once per run (not per
  file) — fail fast before any file discovery happens.

---

## `jobs/builder.py`

```python
def discover_audio_files(input_path: Path, excludes: list[str]) -> list[Path]: ...

def build_jobs(files: list[Path], input_root: Path, source_root: Path | None,
                output_root: Path, preset: PresetConfig,
                lossy_action: LossyAction | None, no_lossy_check: bool,
                ffprobe_binary: str, probe_workers: int) -> tuple[list[ConversionJob], list[Path]]:
    """
    Returns (jobs, lossy_files_found).
    - If no_lossy_check: is_lossy_source=None for every job, job_type="convert" always.
    - Else: probe_many() all files first.
        - lossy + lossy_action is None  -> caller (main.py) must abort using lossy_files_found
          before this function's jobs list is even used for execution.
        - lossy + lossy_action == LEAVE  -> job_type="skip" (excluded from execution entirely)
        - lossy + lossy_action == COPY   -> job_type="copy" (raw file copy, no transcode)
        - lossy + lossy_action == CONVERT -> job_type="convert" (proceed normally)
        - not lossy -> job_type="convert" always, regardless of lossy_action
    """
```
- This function does **not** itself raise/abort on missing `lossy_action` — it returns the
  `lossy_files_found` list and lets `main.py` decide (keeps the module testable without needing to
  catch a control-flow exception for the normal "found lossy files, need to ask" case).
- `job_type="skip"` jobs are dropped from the list returned for execution but should still be
  reported in `--dry-run` output and counted in the final summary as `SKIPPED (lossy, leave)`.

---

## `history/db.py`

Refactor of the original `ConversionDB`, same SQLite table plus one column:

```sql
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT,
    dest_path TEXT,
    job_type TEXT,         -- NEW: 'convert' | 'copy'
    command TEXT,           -- NULL for job_type='copy'
    status TEXT,
    error_msg TEXT,
    stdout TEXT,
    timestamp TEXT,
    UNIQUE(source_path, dest_path)
);
```
- `get_record(source, dest)` / `log_conversion(...)` keep the original signatures, `job_type`
  added as a new parameter with a default so call sites aren't all forced to change at once during
  incremental build-out.
- Resume check in the Execution Runner must also compare `job_type` — a file previously logged as
  `copy` but now requested as `convert` (e.g. user changed `--lossy-action`) must **not** be
  skipped just because `source_path`/`dest_path` match.

---

## `execution/runner.py`

```python
def run_job(job: ConversionJob, backend: ConversionBackend, db: ConversionDB,
            force: bool, stream_callback, progress, master_task) -> JobResult: ...

def run_all(jobs: list[ConversionJob], backend: ConversionBackend, db: ConversionDB,
            force: bool, workers: int, worker_model: str, verbose, progress, master_task) -> dict[str, int]:
```
- For `job_type == "copy"`: uses `shutil.copy2`, no backend call at all.
- For `job_type == "convert"`: resume-checks history, then calls `backend.run(job, stream_callback)`.
- After a successful convert **or** copy: calls `sidecars.manager.copy_lyrics` /
  `copy_covers` exactly once (this is where sidecar handling plugs in — keep it backend-agnostic,
  it never talks to the backend).
- Preserves the original's `ThreadPoolExecutor` pattern; `worker_model == "process"` swaps in
  `ProcessPoolExecutor` (mainly useful for the `native_ffmpeg` backend where each job is genuinely
  CPU-bound and GIL-independent subprocess calls don't benefit much from threads vs processes
  either way — document this as a minor/optional enhancement, not a hard requirement).

---

## `ui/progress_view.py`

Thin extraction of the original script's `rich` `Live`/`Layout`/`Progress`/`Panel` wiring into a
class, e.g. `class ProgressView`, with `start()`, `update_log(lines: list[str])`, `stop()` — so
`main.py` doesn't contain UI rendering code inline.

---

## `cli/args.py`

```python
def parse_args(argv: list[str] | None = None) -> Namespace: ...
def validate_args(args: Namespace) -> None:
    """Implements the cross-flag rules in 01-config-schema.md §3. Raises ArgValidationError."""
```

---

## `main.py`

Orchestration only — no business logic lives here:
1. `parse_args` → `validate_args`
2. `load_settings`, `load_presets` → `get_preset`
3. `registry.resolve_backend_for_run` → `registry.get_backend` (validates environment)
4. `pathing.resolver.validate_source_path` if `--source-path` given
5. `jobs.builder.discover_audio_files` → `jobs.builder.build_jobs`
6. **Lossy gate**: if `lossy_files_found` non-empty and `args.lossy_action is None` and not
   `--dry-run`/`--list-lossy`/`--no-lossy-check` → print files + required flag, `sys.exit(1)`
   **before** touching `ConversionDB` or the thread pool.
7. `--list-lossy` / `--dry-run` → print and exit, no execution.
8. `execution.runner.run_all(...)`
9. Print final summary (kept from original: Success/Skipped/Failed counts).
