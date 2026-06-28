"""tests/test_app_context.py: Tests for AppContext and build_context()."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAppContext:
    """Tests for AppContext dataclass."""

    def test_app_context_is_frozen(self):
        from dataclasses import FrozenInstanceError

        from src.app.context import AppContext

        ctx = AppContext(
            args=MagicMock(),
            settings=MagicMock(),
            preset=MagicMock(),
            backend=MagicMock(),
            backend_name=MagicMock(),
            db_path=Path("/tmp/history.db"),
            workers=4,
            worker_model="thread",
            execution_mode=MagicMock(value="hybrid"),
            verbose=False,
        )

        with pytest.raises(FrozenInstanceError):
            ctx.workers = 8

    def test_app_context_fields(self):
        from src.app.context import AppContext

        mock_args = MagicMock()
        mock_settings = MagicMock()
        mock_preset = MagicMock()
        mock_backend = MagicMock()
        mock_backend_name = MagicMock()
        db_path = Path("/tmp/history.db")

        ctx = AppContext(
            args=mock_args,
            settings=mock_settings,
            preset=mock_preset,
            backend=mock_backend,
            backend_name=mock_backend_name,
            db_path=db_path,
            workers=4,
            worker_model="thread",
            execution_mode=MagicMock(value="hybrid"),
            verbose=True,
        )

        assert ctx.args is mock_args
        assert ctx.settings is mock_settings
        assert ctx.preset is mock_preset
        assert ctx.backend is mock_backend
        assert ctx.db_path == db_path
        assert ctx.workers == 4
        assert ctx.worker_model == "thread"
        assert ctx.verbose is True


class TestBuildContext:
    """Tests for build_context() error paths via integration of sys.exit calls."""

    def test_build_context_loads_presets_on_valid_args(self, tmp_path, monkeypatch):
        """With valid args, build_context loads presets successfully."""
        from src.app.context import build_context

        mock_args = MagicMock()
        mock_args.preset = "test-preset"
        mock_args.backend = None
        mock_args.auto_detect_backend = None
        mock_args.db = None
        mock_args.workers = None
        mock_args.worker_model = None
        mock_args.execution_mode = "hybrid"
        mock_args.verbose = False

        mock_preset = MagicMock()
        mock_preset.name = "test-preset"

        # Set up a complete settings.yaml in tmp_path (load_settings requires
        # backend/history/execution/logging top-level keys).
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(
            "backend:\n"
            "  default: native_ffmpeg\n"
            "  auto_detect: false\n"
            "  native_dbpoweramp:\n"
            "    coreconverter_path: C:\\Program Files\\dBpoweramp\\CoreConverter.exe\n"
            "  wine_dbpoweramp:\n"
            "    wine_binary: /usr/bin/wine\n"
            "    wine_prefix: /root/.wine\n"
            "    coreconverter_path: C:\\Program Files\\dBpoweramp\\CoreConverter.exe\n"
            "    winepath_binary: /usr/bin/winepath\n"
            "  native_ffmpeg:\n"
            "    ffmpeg_binary: ffmpeg\n"
            "    flac_binary: flac\n"
            "    lame_binary: lame\n"
            "    opusenc_binary: opusenc\n"
            "history:\n"
            "  db_path: history.db\n"
            "execution:\n"
            "  default_workers: 4\n"
            "  probe_workers: 4\n"
            "  worker_model: thread\n"
            "  execution_mode: hybrid\n"
            "logging:\n"
            "  level: INFO\n"
        )
        presets_file = tmp_path / "presets.yaml"
        presets_file.write_text(
            "presets:\n"
            "  test-preset:\n"
            "    ext: .flac\n"
            "    backends:\n"
            "      native_ffmpeg:\n"
            "        tool: ffmpeg\n"
            "        args: ['-c:a', 'flac']\n"
        )

        monkeypatch.chdir(tmp_path)

        # Mock backend detection and instantiation to avoid requiring real backends
        with patch("src.backends.registry.detect_backend_for_run", return_value=MagicMock(value="native_ffmpeg")):
            with patch("src.backends.registry.get_backend") as mock_get:
                mock_backend = MagicMock()
                mock_backend.supports.return_value = True
                mock_get.return_value = mock_backend

                ctx = build_context(mock_args)

        assert ctx.preset.name == "test-preset"
        # build_context passes the db_path value from settings verbatim; the
        # caller is responsible for resolving it relative to the config root.
        assert ctx.db_path == Path("history.db")
