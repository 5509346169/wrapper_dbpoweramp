"""tests/test_backend_quoting.py: Tests for argument quoting in both dBpoweramp backends.

These cover the bug where preset args containing spaces (e.g. the qaac-cvbr-256
``-codec="LC AAC"`` flag) were silently stripped of their quotes and then
re-tokenised by CreateProcessW, causing CoreConverter to see ``-codec=LC`` plus
the orphan ``AAC`` token. The wrappers must re-wrap such values in literal
double quotes so the value survives Popen's command-line assembly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models.types import Backend, BackendPresetArgs, PresetConfig


def _path_str(s: str) -> Path:
    """Path with a deterministic __str__ that always returns the original."""
    p = MagicMock(spec=Path)
    p.__str__ = lambda self: s  # noqa: ARG005
    return p


def _settings_native(
    coreconverter: str = "C:/Program Files/dBpoweramp/CoreConverter.exe",
) -> "object":
    """Build a real Settings instance (not a MagicMock) so nested attributes work."""
    from src.config.settings_loader import Settings

    return Settings(
        backend=_backend_cfg(coreconverter=coreconverter),
        tools=_tools_cfg(),
        history=_history_cfg(),
        execution=_execution_cfg(),
        logging=_logging_cfg(),
    )


def _settings_wine() -> "object":
    """Build a real Settings instance with the Wine backend fields populated."""
    from src.config.settings_loader import Settings

    return Settings(
        backend=_backend_cfg(wine=True),
        tools=_tools_cfg(),
        history=_history_cfg(),
        execution=_execution_cfg(),
        logging=_logging_cfg(),
    )


def _backend_cfg(
    coreconverter: str | None = None,
    wine: bool = False,
) -> "object":
    from src.config.settings_loader import (
        BackendConfig,
        NativeBackendConfig,
        NativeDbpowerampConfig,
        WineBackendConfig,
    )

    return BackendConfig(
        default="native_dbpoweramp",
        auto_detect=True,
        wine_dbpoweramp=WineBackendConfig(
            wine_binary=Path("/usr/bin/wine"),
            wine_prefix=Path("/tmp/.wine"),
            coreconverter_path=Path(coreconverter or "C:/Program Files/dBpoweramp/CoreConverter.exe"),
            winepath_binary=Path("/usr/bin/winepath"),
        ) if wine else WineBackendConfig(
            wine_binary=Path("wine"),
            wine_prefix=Path("~/.wine"),
            coreconverter_path=Path("C:/Program Files/dBpoweramp/CoreConverter.exe"),
            winepath_binary=Path("winepath"),
        ),
        native_dbpoweramp=NativeDbpowerampConfig(
            coreconverter_path=Path(coreconverter or "C:/Program Files/dBpoweramp/CoreConverter.exe"),
        ),
        native_ffmpeg=NativeBackendConfig(
            ffmpeg_binary="ffmpeg",
            flac_binary="flac",
            lame_binary="lame",
            opusenc_binary="opusenc",
        ),
    )


def _tools_cfg() -> "object":
    from src.config.settings_loader import ToolsConfig
    return ToolsConfig()


def _history_cfg() -> "object":
    from src.config.settings_loader import HistoryConfig
    return HistoryConfig(db_path="history.db")


def _execution_cfg() -> "object":
    from src.config.settings_loader import ExecutionConfig
    return ExecutionConfig(
        default_workers=4, probe_workers=16,
        worker_model="thread", execution_mode="hybrid",
    )


def _logging_cfg() -> "object":
    from src.config.settings_loader import LoggingConfig
    return LoggingConfig(level="INFO")


def _preset(args: list[str], backend: Backend) -> PresetConfig:
    preset = MagicMock(spec=PresetConfig)
    preset.ext = ".m4a"
    preset.backends = {
        backend: BackendPresetArgs(encoder="m4a QAAC (iTunes)", args=list(args)),
    }
    return preset


def _fake_proc_with_empty_stdout():
    """Build a MagicMock Popen whose stdout is a real closeable stream.

    The real backend iterates ``proc.stdout`` line-by-line and then calls
    ``proc.stdout.close()`` — both need a file-like object with a
    ``close`` method (a plain ``iter([])`` raises AttributeError on
    ``.close()``). ``io.StringIO()`` satisfies both constraints.
    """
    import io

    fake_proc = MagicMock()
    fake_proc.stdout = io.StringIO()
    return fake_proc


class TestNativeBackendQuoting:
    """The native backend must wrap extra args containing spaces."""

    def test_quoted_arg_with_space_preserved(self):
        from src.backends.native_dbpoweramp import NativeDbpowerampBackend

        backend = NativeDbpowerampBackend(_settings_native())
        job = MagicMock()
        job.infile = _path_str("C:/in.m4a")
        job.outfile = _path_str("C:/out.m4a")
        job.preset = _preset(['-codec="LC AAC"'], Backend.NATIVE_DBPOWERAMP)

        captured: dict[str, object] = {}
        fake_proc = _fake_proc_with_empty_stdout()

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return fake_proc

        with patch("src.backends.native_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
            backend.run(job, stream_callback=None)

        cmd = captured["cmd"]
        # The wrapper strips the user's embedded quotes (so CoreConverter
        # doesn't treat them as a value terminator) and re-wraps the
        # space-containing value in its own quotes. The result is a single
        # quoted token '-codec="LC AAC"' (the inner quotes are decorative
        # for CoreConverter, which strips them again).
        assert '"-codec=LC AAC"' in cmd, f"missing quoted -codec in {cmd!r}"
        # It must NOT appear as two naked tokens (the bug we're guarding
        # against).
        assert " -codec=LC AAC " not in cmd
        assert " -codec=LC -bitrate" not in cmd  # bare -codec would split

    def test_unquoted_arg_not_re_wrapped(self):
        from src.backends.native_dbpoweramp import NativeDbpowerampBackend

        backend = NativeDbpowerampBackend(_settings_native())
        job = MagicMock()
        job.infile = _path_str("C:/in.m4a")
        job.outfile = _path_str("C:/out.m4a")
        job.preset = _preset(["-keepsr"], Backend.NATIVE_DBPOWERAMP)

        captured: dict[str, object] = {}
        fake_proc = _fake_proc_with_empty_stdout()

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return fake_proc

        with patch("src.backends.native_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
            backend.run(job, stream_callback=None)

        cmd = captured["cmd"]
        assert "-keepsr" in cmd
        # No whitespace in -keepsr → no quotes added.
        assert '"-keepsr"' not in cmd, f"should not be wrapped: {cmd!r}"

    def test_full_qaac_cvbr_preset_emits_intact(self):
        from src.backends.native_dbpoweramp import NativeDbpowerampBackend

        backend = NativeDbpowerampBackend(_settings_native())
        job = MagicMock()
        job.infile = _path_str("C:/src.m4a")
        job.outfile = _path_str("C:/dst.m4a")
        job.preset = _preset([
            '-cbr_vbr="cVBR"',
            '-bitrate="256"',
            '-codec="LC AAC"',
            "-keepsr",
        ], Backend.NATIVE_DBPOWERAMP)

        captured: dict[str, object] = {}
        fake_proc = _fake_proc_with_empty_stdout()

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return fake_proc

        with patch("src.backends.native_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
            backend.run(job, stream_callback=None)

        cmd = captured["cmd"]
        # Single-token-value flags lose their embedded quotes (CoreConverter
        # strips them as value terminators), so they're emitted bare.
        assert "-cbr_vbr=cVBR" in cmd, cmd
        assert "-bitrate=256" in cmd, cmd
        # The space-bearing value is re-quoted so the whole token survives
        # CreateProcessW tokenisation. The inner quotes around LC AAC are
        # decorative (CoreConverter strips them).
        assert '"-codec=LC AAC"' in cmd, cmd
        # -keepsr has no space → bare.
        assert "-keepsr" in cmd, cmd
        # Crucially: the orphan "AAC" must not appear as a separate token
        # anywhere in the cmd line.
        for token in cmd.split():
            assert token != "AAC", f"orphan token leaked into cmd: {cmd!r}"


class TestWineBackendQuoting:
    """The wine backend applies the same quoting rule."""

    def test_quoted_arg_with_space_preserved(self):
        from src.backends.wine_dbpoweramp import WineDbpowerampBackend

        backend = WineDbpowerampBackend(_settings_wine())
        job = MagicMock()
        job.infile = _path_str("Z:/in.m4a")
        job.outfile = _path_str("Z:/out.m4a")
        job.preset = _preset(['-codec="LC AAC"'], Backend.WINE_DBPOWERAMP)

        captured: dict[str, object] = {}
        fake_proc = _fake_proc_with_empty_stdout()

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return fake_proc

        with patch("src.backends.wine_dbpoweramp.to_wine_path", side_effect=lambda p, *_: str(p)):
            with patch("src.backends.wine_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
                backend.run(job, stream_callback=None)

        cmd = captured["cmd"]
        # Same shape as the native test: the wrapper re-quotes space-bearing
        # values so the arg survives CreateProcessW tokenisation.
        assert '"-codec=LC AAC"' in cmd, f"missing quoted -codec in {cmd!r}"
        # The orphan "AAC" must not leak as a separate token.
        for token in cmd.split():
            assert token != "AAC", f"orphan token leaked into cmd: {cmd!r}"


class TestNativeBackendLongPathStaging:
    """Long-path workaround: when enabled, CoreConverter must see short
    paths; the long-path output is implicitly updated because on NTFS
    the short path is the same physical file as the long path."""

    def test_long_paths_off_passes_long_paths_through(self):
        from src.backends.native_dbpoweramp import NativeDbpowerampBackend

        backend = NativeDbpowerampBackend(_settings_native())
        # A path short enough that staging won't kick in even if the flag
        # were on. We assert that the cmd preserves the long path verbatim.
        job = MagicMock()
        job.infile = Path("C:/Music/in.m4a")
        job.outfile = Path("C:/Music/out.m4a")
        job.preset = _preset(["-keepsr"], Backend.NATIVE_DBPOWERAMP)

        captured: dict[str, object] = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            proc = MagicMock()
            from io import StringIO
            proc.stdout = StringIO()
            proc.wait.return_value = 0
            return proc

        with patch("src.backends.native_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
            result = backend.run(job, stream_callback=None)

        assert result.status == "SUCCESS", result.error_msg
        assert '-infile="C:\\Music\\in.m4a"' in captured["cmd"]

    def test_long_paths_on_with_short_resolution_stages(self):
        from src.backends.native_dbpoweramp import NativeDbpowerampBackend
        from src.config.settings_loader import (
            BackendConfig,
            NativeDbpowerampConfig,
        )

        # Build a settings instance with long_paths=True.
        base = _settings_native()
        settings = type(base)(
            backend=BackendConfig(
                default=base.backend.default,
                auto_detect=base.backend.auto_detect,
                wine_dbpoweramp=base.backend.wine_dbpoweramp,
                native_dbpoweramp=NativeDbpowerampConfig(
                    coreconverter_path=base.backend.native_dbpoweramp.coreconverter_path,
                    long_paths=True,
                ),
                native_ffmpeg=base.backend.native_ffmpeg,
            ),
            tools=base.tools,
            history=base.history,
            execution=base.execution,
            logging=base.logging,
        )

        backend = NativeDbpowerampBackend(settings)

        # Real long paths on disk so GetShortPathNameW resolves them.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            long_infile = tmp_p / ("a" * 200) / "in.m4a"
            long_outfile = tmp_p / ("a" * 200) / "out.m4a"
            long_infile.parent.mkdir(parents=True, exist_ok=True)
            long_outfile.parent.mkdir(parents=True, exist_ok=True)
            long_infile.write_bytes(b"x" * 100)

            job = MagicMock()
            job.infile = long_infile
            job.outfile = long_outfile
            job.preset = _preset(["-keepsr"], Backend.NATIVE_DBPOWERAMP)

            captured: dict[str, object] = {}

            def fake_popen(cmd, **kwargs):
                captured["cmd"] = cmd
                import re
                m = re.search(r'-outfile="([^"]+)"', cmd)
                assert m is not None, f"cmd missing -outfile=: {cmd!r}"
                captured["short_outfile"] = m.group(1)

                # Simulate CoreConverter writing the output to the short
                # path. On NTFS, the short path is the same file as the
                # long path (same inode), so the long-path file is also
                # written.
                Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
                Path(m.group(1)).write_bytes(b"converted-audio")

                proc = MagicMock()
                from io import StringIO
                proc.stdout = StringIO()
                proc.wait.return_value = 0
                return proc

            with patch("src.backends.native_dbpoweramp.subprocess.Popen", side_effect=fake_popen):
                result = backend.run(job, stream_callback=None)

            assert result.status == "SUCCESS", result.error_msg
            cmd = captured["cmd"]
            # The short path was passed to CoreConverter, NOT the long one.
            assert str(long_infile) not in cmd, (
                f"long path leaked into cmd despite long_paths=True: {cmd!r}"
            )
            assert str(long_outfile) not in cmd, (
                f"long outfile leaked into cmd: {cmd!r}"
            )
            # Because short and long paths share an inode on NTFS, the
            # write to the short path is immediately visible at the long
            # path — no explicit rename needed.
            assert long_outfile.exists(), "long-path output not visible after CoreConverter exit"
            assert long_outfile.read_bytes() == b"converted-audio", (
                "long-path output content does not match what CoreConverter wrote"
            )
