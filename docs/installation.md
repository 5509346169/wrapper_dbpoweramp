# Installation

This guide covers installing dependencies for dBpoweramp Wrapper on Linux and Windows.

---

## Requirements

### Python

- **Python 3.10** or higher
- Required packages: `pyyaml`, `rich`

### FFmpeg (for `native_ffmpeg` backend)

- `ffmpeg` - Audio/video converter
- `ffprobe` - Audio stream analyzer (comes with ffmpeg)

### dBpoweramp (optional, for dBpoweramp backends)

- **Linux**: Wine + dBpoweramp installer
- **Windows**: dBpoweramp Reference

---

## Linux Installation

### Arch Linux / CachyOS

Install system packages:

```sh
sudo pacman -S ffmpeg wine python python-pip python-yaml python-rich
```

For FDK AAC support (for `aac-vbr-high` preset):

```sh
# Install ffmpeg-full from AUR (includes libfdk_aac)
yay -S ffmpeg-full
```

### Debian / Ubuntu

Install system packages:

```sh
sudo apt update
sudo apt install ffmpeg wine python3 python3-pip python3-yaml python3-rich
```

For FDK AAC support, you'll need to rebuild FFmpeg or use a third-party repository.

### Fedora

Install system packages:

```sh
sudo dnf install ffmpeg wine python3 python3-pip python3-pyyaml python3-rich
```

### Python Dependencies

Install Python packages:

```sh
pip install -r requirements.txt
```

Or with uv:

```sh
uv sync
```

### Wine Setup

#### Initialize Wine Prefix

```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
```

#### Install dBpoweramp

1. Download dBpoweramp Reference from https://www.dbpoweramp.com/
2. Run the installer under Wine:

```sh
WINEPREFIX=~/.wine-dbpoweramp wine ~/Downloads/dBpowerampReference.exe
```

Follow the installation wizard. Install to the default location: `C:\Program Files\dBpoweramp`

---

## Windows Installation

### Python

Download and install Python 3.10+ from https://python.org/

During installation, check "Add Python to PATH".

### dBpoweramp

1. Download dBpoweramp Reference from https://www.dbpoweramp.com/
2. Run the installer
3. Install to the default location: `C:\Program Files\dBpoweramp`

### Python Dependencies

Open Command Prompt or PowerShell:

```sh
pip install pyyaml rich
```

Or install from requirements:

```sh
pip install -r requirements.txt
```

---

## Verification

### Test FFmpeg Installation

```sh
ffmpeg -version
ffprobe -version
```

Expected output:
```
ffmpeg version X.X.X
configuration: ...
libavutil      X.X.X
libavcodec    X.X.X
libavformat   X.X.X
libswscale    X.X.X
libswresample X.X.X
libpostproc   X.X.X
libavfilter   X.X.X
libavdevice   X.X.X
```

### Test Wine Installation (Linux)

```sh
wine --version
winepath --version
```

Expected output:
```
wine-X.X.X
```

### Test dBpoweramp Installation (Windows)

```sh
"C:\Program Files\dBpoweramp\CoreConverter.exe" -version
```

Or on Linux:

```sh
WINEPREFIX=~/.wine-dbpoweramp wine "C:\Program Files\dBpoweramp\CoreConverter.exe" -version
```

### Test Python Installation

```sh
python --version
pip --version
```

### Test Python Packages

```sh
python -c "import yaml; import rich; print('OK')"
```

---

## Troubleshooting

### FFmpeg Not Found

**Error:**
```
BackendError: ffmpeg binary 'ffmpeg' not found on PATH
```

**Solution:**

Linux:
```sh
which ffmpeg  # Check if installed
sudo pacman -S ffmpeg  # Arch
sudo apt install ffmpeg  # Debian/Ubuntu
sudo dnf install ffmpeg  # Fedora
```

Windows:
Download from https://ffmpeg.org/download.html or use a package manager like Chocolatey:
```powershell
choco install ffmpeg
```

### Wine Not Found

**Error:**
```
BackendError: 'wine' not found on PATH
```

**Solution:**

Linux:
```sh
sudo pacman -S wine    # Arch/CachyOS
sudo apt install wine  # Debian/Ubuntu
sudo dnf install wine  # Fedora
```

### CoreConverter Not Found

**Error:**
```
BackendError: CoreConverter not found at 'C:\Program Files\dBpoweramp\CoreConverter.exe'
```

**Solution:**

1. Verify dBpoweramp is installed
2. Check the path in `settings.yaml`
3. On Windows, try reinstalling dBpoweramp

Linux:
```sh
WINEPREFIX=~/.wine-dbpoweramp wine "C:\Program Files\dBpoweramp\CoreConverter.exe" -help
```

### FDK AAC Not Found

**Error:**
```
Encoder 'libfdk_aac' is not available in this ffmpeg build
```

**Solution:**

Linux (Arch):
```sh
yay -S ffmpeg-full
```

Linux (Debian/Ubuntu):
```sh
# Add repository or rebuild FFmpeg with FDK AAC
sudo apt-add-repository ppa:mc3man/trusty-media
sudo apt update
sudo apt install ffmpeg
```

Windows:
Download an FFmpeg build with FDK AAC from https://www.gyan.dev/ffmpeg/builds/

### Wine Prefix Issues

**Error:**
```
BackendError: WINEPREFIX '~/.wine-dbpoweramp' does not exist
```

**Solution:**
```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
# Then reinstall dBpoweramp
```

### Python Import Errors

**Error:**
```
ModuleNotFoundError: No module named 'yaml'
```

**Solution:**
```sh
pip install pyyaml rich
```

---

## Configuration

### Default settings.yaml

The tool works out of the box with default settings. You may want to customize:

```yaml
backend:
  default: "native_ffmpeg"
  auto_detect: true
  native_dbpoweramp:
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
  wine_dbpoweramp:
    wine_binary: "wine"
    wine_prefix: "~/.wine-dbpoweramp"
    coreconverter_path: "C:\\Program Files\\dBpoweramp\\CoreConverter.exe"
    winepath_binary: "winepath"
  native_ffmpeg:
    ffmpeg_binary: "ffmpeg"
    flac_binary: "flac"
    lame_binary: "lame"
    opusenc_binary: "opusenc"

execution:
  default_workers: 4
  probe_workers: 8
  worker_model: "thread"

history:
  db_path: "conversion_history.db"
```

### Changing Default Backend

To use dBpoweramp by default on Windows:

```yaml
backend:
  default: "native_dbpoweramp"
  auto_detect: true
```

---

## Docker (Optional)

For isolated execution, you can run in Docker:

### Dockerfile

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    wine \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "main.py", "-h"]
```

### Build and Run

```sh
docker build -t dbpamp-wrapper .
docker run --rm -v ~/Music:/music dbpamp-wrapper -I /music -O /output -p flac-lossless
```

Note: Wine in Docker requires additional configuration and may have limited functionality.

---

## Next Steps

- Read the [CLI Reference](cli.md) for usage examples
- Read the [Configuration Reference](configuration.md) for customization options
- Read the [Workflow](workflow.md) to understand how conversions work
