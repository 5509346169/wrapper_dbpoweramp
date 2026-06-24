r"""tests/test_dbpoweramp_cli.py: Lock in CLI quoting for the dBpoweramp backends.

These tests guard against a regression where paths containing spaces (e.g.
``C:\Users\Windows 10\Music\...``) would be split by dBpoweramp's own
CoreConverter CLI parser, producing errors like::

    Audio Source: \"C:\Users\Windows
    Audio Destination: \"C:\Users\Windows
    Error: Unable to load decoder for file type '.', codec not installed?

Root cause: CoreConverter uses its own whitespace-splitting parser rather than
the standard Windows CommandLineToArgvW. When paths contain spaces, the
command line must wrap the *value* in literal double quotes *in the raw
command-line string* — and Python's subprocess.list2cmdline escapes any
embedded " with a backslash, which CoreConverter then reads as a literal
backslash. The fix is to build the command line as a single pre-formatted
string and pass it to subprocess.Popen with shell=False, bypassing
list2cmdline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from src.backends.native_dbpoweramp import NativeDbpowerampBackend
from src.backends.wine_dbpoweramp import WineDbpowerampBackend
from src.config.settings_loader import (
    BackendConfig,
    ExecutionConfig,
    HistoryConfig,
    LoggingConfig,
    NativeBackendConfig,
    NativeDbpowerampConfig,
    Settings,
    ToolsConfig,
    WineBackendConfig,
)
from src.models.types import (
    Backend,
    BackendPresetArgs,
    ConversionJob,
    PresetConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings() -> Settings:
    """Build a Settings object with both dBpoweramp backends configured."""
    return Settings(
        backend=BackendConfig(
            default="native_dbpoweramp",
            auto_detect=False,
            wine_dbpoweramp=WineBackendConfig(
                wine_binary="wine",
                wine_prefix=Path("/tmp/wine"),
                coreconverter_path=r"C:\Program Files\dBpoweramp\CoreConverter.exe",
                winepath_binary="winepath",
            ),
            native_dbpoweramp=NativeDbpowerampConfig(
                coreconverter_path=r"C:\Program Files\dBpoweramp\CoreConverter.exe",
            ),
            native_ffmpeg=NativeBackendConfig(
                ffmpeg_binary="ffmpeg",
                flac_binary="flac",
                lame_binary="lame",
                opusenc_binary="opusenc",
            ),
        ),
        tools=ToolsConfig(),
        history=HistoryConfig(db_path="conversion_history.db"),
        execution=ExecutionConfig(
            default_workers=4,
            probe_workers=8,
            worker_model="thread",
        ),
        logging=LoggingConfig(level="INFO"),
    )


def _stub_job(tmp_path: Path) -> ConversionJob:
    """A conversion job whose paths deliberately contain a space."""
    infile = tmp_path / "Music Space" / "song with space.flac"
    outfile = tmp_path / "Out Space" / "song with space.m4a"
    preset = PresetConfig(
        name="test",
        ext="m4a",
        backends={
            Backend.NATIVE_DBPOWERAMP: BackendPresetArgs(
                encoder="m4a FDK (AAC)",
                args=["-m", "5"],
            ),
            Backend.WINE_DBPOWERAMP: BackendPresetArgs(
                encoder="m4a FDK (AAC)",
                args=["-m", "5"],
            ),
        },
    )
    return ConversionJob(
        infile=infile,
        outfile=outfile,
        preset=preset,
        job_type="convert",
    )


def _fake_popen_success() -> mock.Mock:
    """Return a mock that simulates a successful (exit 0) CoreConverter process."""
    m = mock.Mock()
    # stdout needs .close() and be iterable; empty iterator is fine.
    m.stdout = mock.MagicMock()
    m.stdout.__iter__.return_value = iter([])
    m.stdout.close.return_value = None
    m.wait.return_value = 0
    return m


# ---------------------------------------------------------------------------
# Native backend tests
# ---------------------------------------------------------------------------


def test_native_backend_quotes_infile_and_outfile_values(tmp_path: Path) -> None:
    """CoreConverter requires -infile="<path>" with embedded double quotes when
    the path contains spaces. The command-line string passed to
    subprocess.Popen must contain literal double quotes around each path
    *and* the value, and must NOT contain backslash-escaped quotes (which
    is what list2cmdline would produce from a list form)."""
    backend = NativeDbpowerampBackend(_make_settings())
    job = _stub_job(tmp_path)

    with mock.patch(
        "src.backends.native_dbpoweramp.subprocess.Popen",
        return_value=_fake_popen_success(),
    ) as popen_mock:
        backend.run(job, stream_callback=None)

    cmd = popen_mock.call_args.args[0]
    # cmd must be a single string (not a list) to bypass list2cmdline escaping.
    assert isinstance(cmd, str), f"expected string command line, got list/tuple: {cmd!r}"

    # The string command line must contain literal -infile="..." and -outfile="..." with
    # the full paths, and those paths must NOT have been backslash-escaped.
    assert f'-infile="{job.infile}"' in cmd, f"-infile value not properly quoted: {cmd!r}"
    assert f'-outfile="{job.outfile}"' in cmd, f"-outfile value not properly quoted: {cmd!r}"
    assert '-convert_to="m4a FDK (AAC)"' in cmd, f"-convert_to value not quoted: {cmd!r}"
    assert '\\"' not in cmd, (
        f"Embedded quotes were backslash-escaped — CoreConverter would see "
        f"backslash literals in the path. Command line: {cmd!r}"
    )


def test_native_backend_cmd_is_passed_as_string_no_shell(tmp_path: Path) -> None:
    """shell=False is the project's stated contract — guard against regressing
    to shell=True (security + correctness)."""
    backend = NativeDbpowerampBackend(_make_settings())
    job = _stub_job(tmp_path)

    with mock.patch(
        "src.backends.native_dbpoweramp.subprocess.Popen",
        return_value=_fake_popen_success(),
    ) as popen_mock:
        backend.run(job, stream_callback=None)

    kwargs = popen_mock.call_args.kwargs
    assert kwargs.get("shell") is False
    assert isinstance(popen_mock.call_args.args[0], str)


def test_native_backend_strips_embedded_quotes_from_extra_args(tmp_path: Path) -> None:
    """extra_args from presets.yaml may contain decorative quotes (e.g.
    -encoding=\"SLOW\"); CoreConverter would treat the embedded quote as a
    value terminator, so the backend must strip them before emitting the
    command line."""
    backend = NativeDbpowerampBackend(_make_settings())
    job = _stub_job(tmp_path)
    job.preset.backends[Backend.NATIVE_DBPOWERAMP] = BackendPresetArgs(
        encoder="mp3 (LAME)",
        args=["-V", "0", '-encoding="SLOW"'],
    )

    with mock.patch(
        "src.backends.native_dbpoweramp.subprocess.Popen",
        return_value=_fake_popen_success(),
    ) as popen_mock:
        backend.run(job, stream_callback=None)

    cmd = popen_mock.call_args.args[0]
    assert '-encoding=SLOW' in cmd, (
        f"Embedded quotes in extra_args should be stripped. Command line: {cmd!r}"
    )
    assert '\\"' not in cmd, f"Backslash-escaped quotes leaked through: {cmd!r}"


# ---------------------------------------------------------------------------
# Wine backend tests
# ---------------------------------------------------------------------------


def test_wine_backend_quotes_infile_and_outfile_values(tmp_path: Path) -> None:
    """Same quoting guarantee for the Wine backend."""
    backend = WineDbpowerampBackend(_make_settings())
    job = _stub_job(tmp_path)

    # winepath returns a Windows-style Z:-prefixed path; mock it deterministically.
    with mock.patch(
        "src.backends.wine_dbpoweramp.to_wine_path",
        side_effect=lambda p, *_: f"Z:\\{p.name}",
    ), mock.patch(
        "src.backends.wine_dbpoweramp.subprocess.Popen",
        return_value=_fake_popen_success(),
    ) as popen_mock:
        backend.run(job, stream_callback=None)

    cmd = popen_mock.call_args.args[0]
    assert isinstance(cmd, str), f"expected string command line, got list/tuple: {cmd!r}"
    assert '-infile="Z:\\song with space.flac"' in cmd, (
        f"wine -infile value not properly quoted: {cmd!r}"
    )
    assert '-outfile="Z:\\song with space.m4a"' in cmd, (
        f"wine -outfile value not properly quoted: {cmd!r}"
    )
    assert '\\"' not in cmd, f"Backslash-escaped quotes leaked through: {cmd!r}"

