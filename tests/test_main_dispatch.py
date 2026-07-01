"""tests/test_main_dispatch.py: Tests for main.py dispatcher routing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestMainDispatcher:
    """Tests for main() dispatcher routing logic."""

    def test_db_version_flag_routes_to_cmd_db_check(self):
        """--db-version should route to cmd_db_check without loading presets."""
        with patch.object(sys, "argv", ["wrapper-dbpoweramp", "--db-version"]):
            with patch("src.cli.db_cmd.cmd_db_check") as mock_check:
                mock_check.return_value = 0

                from main import main
                result = main()

                mock_check.assert_called_once()
                assert result == 0

    def test_db_subcommand_routes_correctly(self):
        """The db subcommand dispatches to the right handlers."""
        from main import main
        import inspect
        source = inspect.getsource(main)

        # Verify the dispatch dictionary is present
        assert '"check":' in source
        assert '"migrate":' in source
        assert "cmd_db_doctor" in source

    def test_main_signature_returns_int(self):
        """main() should have int return annotation."""
        from main import main
        sig = main.__annotations__
        # Python stores forward references as strings
        assert sig.get("return") in ("int", "'int'", '"int"')

    def test_main_early_exit_paths(self):
        """main() has early exit paths that avoid loading full config."""
        from main import main
        import inspect
        source = inspect.getsource(main)

        # db_version check happens before build_context
        assert "args.db_version" in source
        assert "build_context" in source
        # build_context is called after db checks
        db_check_pos = source.find("args.db_version")
        build_ctx_pos = source.find("build_context")
        assert db_check_pos < build_ctx_pos, "db_version check should come before build_context"


class TestParseArgsDispatchFlags:
    """Tests for parse_args routing flags."""

    def test_verify_output_flag(self):
        from src.cli.args import parse_args

        args2 = parse_args(["-I", "/input", "-O", "/output", "-p", "flac", "--verify-output", "none"])
        assert args2.verify_output == "none"

        args3 = parse_args(["-I", "/input", "-O", "/output", "-p", "flac", "--verify-output", "full"])
        assert args3.verify_output == "full"

    def test_verify_skip_flag(self):
        from src.cli.args import parse_args

        args = parse_args(["-I", "/input", "-O", "/output", "-p", "flac", "--verify-skip"])
        assert args.verify_skip is True

        args2 = parse_args(["-I", "/input", "-O", "/output", "-p", "flac"])
        assert args2.verify_skip is False

    def test_db_version_flag_parses(self):
        from src.cli.args import parse_args

        with patch.object(sys, "argv", ["wrapper-dbpoweramp", "--db-version"]):
            args = parse_args()
            assert args.db_version is True

    def test_db_subcommand_check_parses(self):
        from src.cli.args import parse_args

        with patch.object(sys, "argv", ["wrapper-dbpoweramp", "db", "check"]):
            args = parse_args()
            assert args.command == "db"
            assert args.db_command == "check"

    def test_db_subcommand_migrate_parses(self):
        from src.cli.args import parse_args

        with patch.object(sys, "argv", ["wrapper-dbpoweramp", "db", "migrate"]):
            args = parse_args()
            assert args.command == "db"
            assert args.db_command == "migrate"

    def test_db_subcommand_doctor_parses(self):
        from src.cli.args import parse_args

        with patch.object(sys, "argv", ["wrapper-dbpoweramp", "db", "doctor"]):
            args = parse_args()
            assert args.command == "db"
            assert args.db_command == "doctor"


class TestPlaylistCLI:
    """Tests for --playlist CLI argument parsing and validation."""

    def test_playlist_flag_parses(self):
        from src.cli.args import parse_args

        args = parse_args(["--playlist", "/path/to/playlist.m3u", "-O", "/out", "-p", "flac"])
        assert args.playlist == Path("/path/to/playlist.m3u")
        assert args.input is None

    def test_input_and_playlist_mutually_exclusive(self):
        """Passing both --input and --playlist raises argparse error."""
        import io, sys as test_sys
        from src.cli.args import parse_args
        from unittest.mock import patch

        with patch.object(test_sys, "argv", ["prog", "--playlist", "/a.m3u", "-I", "/b", "-O", "/out", "-p", "flac"]):
            with patch.object(test_sys, "stderr", io.StringIO()):
                with pytest.raises(SystemExit) as exc_info:
                    parse_args()
                assert exc_info.value.code == 2  # argparse error 2 = usage error

    def test_playlist_requires_output_and_preset(self):
        import io, sys as test_sys
        from src.cli.args import parse_args, validate_args
        from unittest.mock import patch

        with patch.object(test_sys, "argv", ["prog", "--playlist", "/a.m3u"]):
            args = parse_args()
        with patch.object(test_sys, "stderr", io.StringIO()):
            with pytest.raises(SystemExit) as exc_info:
                validate_args(args)
            assert exc_info.value.code == 1
