---
permalink: /installation/
layout: default
title: Installation
slug: installation
category: getting-started
order: 10
summary: Install Python, FFmpeg, Wine, and (optionally) dBpoweramp on Linux or Windows.
audience: [user]
---

This guide covers installing dependencies for dBpoweramp Wrapper on Linux and Windows.

## Requirements

### Python

- Python 3.10 or higher
- Required packages: `pyyaml`, `rich`, `soundfile`, `miniaudio`, `numpy`, `mutagen`

### FFmpeg (for `native_ffmpeg` backend)

- `ffmpeg` — audio/video converter
- `ffprobe` — audio stream analyzer (ships with `ffmpeg`)

### dBpoweramp (optional, for dBpoweramp backends)

- **Linux**: Wine + dBpoweramp installer
- **Windows**: dBpoweramp Reference

## Linux installation

### Arch Linux / CachyOS

```sh
sudo pacman -S ffmpeg wine python python-pip python-yaml python-rich
```

For FDK AAC support (used by the `aac-vbr-high` preset):

```sh
yay -S ffmpeg-full
```

### Debian / Ubuntu

```sh
sudo apt update
sudo apt install ffmpeg wine python3 python3-pip python3-yaml python3-rich
```

For FDK AAC, rebuild FFmpeg or use a third-party repository.

### Fedora

```sh
sudo dnf install ffmpeg wine python3 python3-pip python3-pyyaml python3-rich
```

### Python dependencies

```sh
pip install -r requirements.txt
```

Or with `uv`:

```sh
uv sync
```

### Wine setup

Initialize the Wine prefix:

```sh
export WINEPREFIX=~/.wine-dbpoweramp
wineboot --init
```

Install dBpoweramp:

1. Download dBpoweramp Reference from <https://www.dbpoweramp.com/>.
2. Run the installer under Wine:

   ```sh
   WINEPREFIX=~/.wine-dbpoweramp wine ~/Downloads/dBpowerampReference.exe
   ```

3. Install to the default location: `C:\Program Files\dBpoweramp`.

## Windows installation

### Python

Download and install Python 3.10+ from <https://python.org/>. During installation, check **Add Python to PATH**.

### dBpoweramp

1. Download dBpoweramp Reference from <https://www.dbpoweramp.com/>.
2. Run the installer.
3. Install to the default location: `C:\Program Files\dBpoweramp`.

### Python dependencies

Open Command Prompt or PowerShell:

```sh
pip install -r requirements.txt
```

## Verification

### Test FFmpeg installation

```sh
ffmpeg -version
ffprobe -version
```

Expected output begins with `ffmpeg version X.X.X` followed by configuration lines.

### Test Wine installation (Linux)

```sh
wine --version
winepath --version
```

### Test dBpoweramp installation (Windows)

```sh
"C:\Program Files\dBpoweramp\CoreConverter.exe" -version
```

Or on Linux:

```sh
WINEPREFIX=~/.wine-dbpoweramp wine "C:\Program Files\dBpoweramp\CoreConverter.exe" -version
```

### Test Python installation

```sh
python --version
pip --version
```

### Test Python packages

```sh
python -c "import yaml; import rich; print('OK')"
```

## Troubleshooting

{% include components/callout.html type="warning" title="BackendError: ffmpeg binary 'ffmpeg' not found on PATH" content="Linux: install via your package manager. Windows: download from <https://ffmpeg.org/download.html> or use Chocolatey (`choco install ffmpeg`)." %}

{% include components/callout.html type="warning" title="BackendError: 'wine' not found on PATH" content="Linux: install via your package manager (`pacman -S wine`, `apt install wine`, `dnf install wine`)." %}

{% include components/callout.html type="warning" title="BackendError: CoreConverter not found" content="Verify dBpoweramp is installed and that the path in `settings.yaml` matches the install location. On Linux, confirm the Wine prefix exists." %}

{% include components/callout.html type="warning" title="Encoder 'libfdk_aac' is not available" content="Install an FFmpeg build with FDK AAC. On Arch: `yay -S ffmpeg-full`. On Windows: download a build from <https://www.gyan.dev/ffmpeg/builds/>." %}

{% include components/callout.html type="warning" title="BackendError: WINEPREFIX does not exist" content="Initialize the prefix with `wineboot --init`, then reinstall dBpoweramp under that prefix." %}

See [Error handling](/error-handling/) for additional runtime errors.

## Configuration

The tool works out of the box with default settings. To customize, edit `settings.yaml`:

```yaml
backend:
  default: "native_dbpoweramp"
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
  probe_workers: 16
  worker_model: "thread"

history:
  db_path: "conversion_history.db"
```

See [Configuration reference](/configuration/) for the full schema.

## Docker (optional)

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

Build and run:

```sh
docker build -t dbpamp-wrapper .
docker run --rm -v ~/Music:/music dbpamp-wrapper -I /music -O /output -p flac-lossless
```

{% include components/callout.html type="note" title="Wine in Docker" content="Requires additional configuration and may have limited functionality." %}

## Next steps

- [CLI reference](/cli/) for usage examples
- [Configuration reference](/configuration/) for customization options
- [Workflow](/workflow/) to understand how conversions run
