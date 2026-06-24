# Backends Reference

This document explains how each conversion backend works, including environment validation, command construction, and platform support.

---

## Overview

The wrapper supports three conversion backends:

| Backend | Platform | Description |
|---------|----------|-------------|
| `native_ffmpeg` | Linux, Windows | FFmpeg encoder, no external dependencies |
| `native_dbpoweramp` | Windows only | Real dBpoweramp CoreConverter.exe |
| `wine_dbpoweramp` | Linux, Windows | dBpoweramp via Wine |

All backends implement the `ConversionBackend` abstract base class defined in `src/backends/base.py`.

---

## Backend Interface

```python
class ConversionBackend(ABC):
    @abstractmethod
    def name(self) -> Backend:
        """Return the backend identifier."""

    @abstractmethod
    def validate_environment(self) -> None:
        """Check that required binaries/paths/prefix exist.
        
        Raises BackendError with a human-readable, fix-it message if
        validation fails.
        """

    @abstractmethod
    def supports(self, preset: PresetConfig) -> bool:
        """Return True iff preset.backends contains this backend's key."""

    @abstractmethod
    def run(
        self,
        job: ConversionJob,
        stream_callback: Optional[Callable[[str], None]],
    ) -> JobResult:
        """Execute the conversion and return a JobResult."""
```

---

## Native FFmpeg Backend

**File:** `src/backends/native_ffmpeg.py`  
**Class:** `NativeFfmpegBackend`

### Description

This backend shells out to `ffmpeg` (or compatible standalone tools like `flac`, `lame`, `opusenc`) for audio encoding. It requires no external dependencies beyond FFmpeg itself.

### Environment Validation

1. Checks that `ffmpeg` binary exists via `shutil.which()` or as an absolute path
2. If a preset has `requires_encoder` set, checks that encoder is in `ffmpeg -encoders` output

### Command Construction

The command is built from the preset's backend configuration:

```yaml
native_ffmpeg:
  tool: "ffmpeg"               # or "flac", "lame", "opusenc"
  args: ["-c:a", "flac", "-compression_level", "5"]
```

**For FFmpeg tool:**
```sh
ffmpeg -y -i <infile> <args> <outfile>
```

**For standalone tools:**
```sh
<tool-binary> <args> <infile> <outfile>
```

### Example Commands

#### FLAC Encoding

```sh
ffmpeg -y -i input.wav -c:a flac -compression_level 5 output.flac
```

#### MP3 V0 VBR

```sh
ffmpeg -y -i input.wav -c:a libmp3lame -q:a 0 output.mp3
```

#### AAC with FDK

```sh
ffmpeg -y -i input.wav -c:a libfdk_aac -vbr 5 output.m4a
```

#### Opus

```sh
ffmpeg -y -i input.wav -c:a libopus -b:a 128k output.opus
```

### Encoder Requirements

| Encoder | Preset | Installation |
|---------|--------|-------------|
| `libmp3lame` | `mp3-v0-vbr`, `mp3-320-cbr` | Usually included in standard builds |
| `libfdk_aac` | `aac-vbr-high` | `ffmpeg-full` from AUR or rebuild |
| `libopus` | `opus-128` | Usually included in standard builds |

### Error Messages

If FDK AAC is not available:
```
Encoder 'libfdk_aac' is not available in this ffmpeg build.
The ffmpeg binary being used does not include this encoder.
On CachyOS/Arch, install a full-featured ffmpeg build:
  sudo pacman -S ffmpeg-full    # from AUR, includes libfdk_aac and others
Or rebuild your ffmpeg preset without this encoder (remove it from your
presets.yaml aac-vbr-high entry's requires_encoder field).
```

---

## Native dBpoweramp Backend

**File:** `src/backends/native_dbpoweramp.py`  
**Class:** `NativeDbpowerampBackend`

### Description

This backend runs dBpoweramp's `CoreConverter.exe` directly on Windows without Wine. It requires dBpoweramp Reference to be installed.

### Platform Support

- **Windows:** Yes (native)
- **Linux:** Not supported (requires Wine)

### Environment Validation

1. Checks that `CoreConverter.exe` exists at the configured path
2. Default path: `C:\Program Files\dBpoweramp\CoreConverter.exe`

### Command Construction

```sh
CoreConverter.exe -infile=<input> -outfile=<output> -convert_to=<encoder> <args>
```

Example:
```sh
"C:\Program Files\dBpoweramp\CoreConverter.exe" \
    -infile="C:\Music\song.wav" \
    -outfile="C:\Converted\song.mp3" \
    -convert_to="mp3 (LAME)" \
    -V 0
```

### Error Messages

If CoreConverter is not found:
```
BackendError: CoreConverter not found at 'C:\Program Files\dBpoweramp\CoreConverter.exe'.
Install dBpoweramp or update the coreconverter_path in settings.yaml:
  backend:
    native_dbpoweramp:
      coreconverter_path: 'C:\Program Files\dBpoweramp\CoreConverter.exe'
```

---

## Wine dBpoweramp Backend

**File:** `src/backends/wine_dbpoweramp.py`  
**Class:** `WineDbpowerampBackend`

### Description

This backend runs dBpoweramp's `CoreConverter.exe` under Wine on Linux (or cross-compiled Wine on Windows). It requires Wine and a Wine prefix with dBpoweramp installed.

### Platform Support

- **Linux:** Yes (primary use case)
- **Windows:** Yes (cross-compiled Wine)

### Environment Validation

1. Resolves `wine` binary via `shutil.which()` or absolute path
2. Resolves `winepath` binary via `shutil.which()` or absolute path
3. Checks that Wine prefix directory exists
4. Runs `wine --version` as a smoke test

### Path Translation

Linux paths must be translated to Windows paths for CoreConverter:

```python
wine_infile = to_wine_path(infile, wine_binary, wine_prefix, winepath_binary)
wine_outfile = to_wine_path(outfile, wine_binary, wine_prefix, winepath_binary)
```

The `to_wine_path()` function:
1. Runs `winepath -w <path>` with `WINEPREFIX` set
2. Returns the Windows-style path string

### Command Construction

```sh
wine CoreConverter.exe -infile=<wine_path> -outfile=<wine_path> -convert_to=<encoder> <args>
```

With environment:
```sh
WINEPREFIX=~/.wine-dbpoweramp wine "C:\Program Files\dBpoweramp\CoreConverter.exe" \
    -infile="Z:\home\user\Music\song.wav" \
    -outfile="Z:\home\user\Converted\song.mp3" \
    -convert_to="mp3 (LAME)" \
    -V 0
```

### Error Messages

#### Wine binary not found:
```
BackendError: 'wine' not found on PATH and is not an absolute path to an existing file.
Install Wine from your distribution's package manager:
  sudo pacman -S wine    (Arch/CachyOS)
  sudo apt install wine  (Debian/Ubuntu)
  sudo dnf install wine (Fedora)
```

#### Wine prefix not found:
```
BackendError: WINEPREFIX '~/.wine-dbpoweramp' does not exist.
Create it by running: WINEPREFIX=~/.wine-dbpoweramp wineboot
Then install dBpoweramp into that prefix using a Windows installer under Wine.
```

#### Wine smoke test failure:
```
BackendError: 'wine --version' exited with code 1.
stderr: <error output>
Wine is installed but appears broken. Try reinstalling Wine.
```

---

## Backend Selection

### Resolution Order

1. **CLI override:** If `--backend NAME` is given, that backend is used.
2. **Auto-detect:** If `auto_detect` is enabled and platform is Windows and preset supports `native_dbpoweramp`, use `native_dbpoweramp`.
3. **Default:** Use `backend.default` from `settings.yaml`.

### Auto-Detection Logic

```python
def detect_backend_for_run(
    cli_backend: Backend | None,
    settings: Settings,
    preset: PresetConfig,
    platform: str,
    auto_detect_override: bool | None = None,
) -> Backend:
    if cli_backend is not None:
        return cli_backend

    auto_detect = (
        auto_detect_override
        if auto_detect_override is not None
        else settings.backend.auto_detect
    )

    if (
        auto_detect
        and platform == "win32"
        and Backend.NATIVE_DBPOWERAMP in preset.backends
    ):
        return Backend.NATIVE_DBPOWERAMP

    return resolve_backend_for_run(None, settings)
```

---

## Preset Compatibility

Not all presets work with all backends:

| Preset | native_ffmpeg | native_dbpoweramp | wine_dbpoweramp |
|--------|---------------|------------------|-----------------|
| `flac-lossless` | Yes | Yes | Yes |
| `mp3-v0-vbr` | Yes | Yes | Yes |
| `mp3-320-cbr` | Yes | Yes | Yes |
| `aac-vbr-high` | Yes | Yes | Yes |
| `qaac-cvbr-256` | **No** | Yes | Yes |
| `opus-128` | Yes | Yes | Yes |

The `qaac-cvbr-256` preset uses Apple's QAAC encoder, which is only available through dBpoweramp (not native FFmpeg).

### Compatibility Check

Before execution, the wrapper checks if the chosen backend supports the selected preset:

```python
if not backend.supports(preset):
    print(
        f"error: backend '{backend_name}' does not support preset '{preset.name}'.\n"
        f"  Choose a different backend with --backend, or pick a preset that supports "
        f"'{backend_name}'."
    )
    sys.exit(1)
```

---

## Output Verification

After every conversion, all backends verify the output file:

```python
def _verify_output_file(job: ConversionJob) -> tuple[bool, str | None]:
    if not job.outfile.exists():
        return False, f"Output file not found: {job.outfile}"
    
    size = job.outfile.stat().st_size
    if size == 0:
        return False, f"Output file is empty: {job.outfile}"
    
    return True, None
```

If verification fails, the job is marked as FAILED even if the tool exited with code 0.

---

## Stream Callback

All backends support a `stream_callback` parameter that receives each line of stdout/stderr:

```python
def run(
    self,
    job: ConversionJob,
    stream_callback: Optional[Callable[[str], None]],
) -> JobResult:
```

When `-v/--verbose` is enabled, this callback is used to display live output from the conversion tool.

---

## Adding a New Backend

To add a new backend:

1. **Create the backend class** in `src/backends/`:
   ```python
   from src.backends.base import ConversionBackend
   from src.models.types import Backend, ConversionJob, JobResult
   
   class MyBackend(ConversionBackend):
       def __init__(self, settings: Settings) -> None:
           ...
       
       def name(self) -> Backend:
           return Backend.MY_BACKEND
       
       def validate_environment(self) -> None:
           ...
       
       def supports(self, preset: PresetConfig) -> bool:
           return Backend.MY_BACKEND in preset.backends
       
       def run(self, job, stream_callback) -> JobResult:
           ...
   ```

2. **Add to the Backend enum** in `src/models/types.py`:
   ```python
   class Backend(str, Enum):
       MY_BACKEND = "my_backend"
       ...
   ```

3. **Register in the registry** in `src/backends/registry.py`:
   ```python
   if name == Backend.MY_BACKEND:
       backend = MyBackend(settings)
   ```

4. **Add to settings.yaml defaults** if needed.

5. **Update presets.yaml** to include the new backend in any presets.
