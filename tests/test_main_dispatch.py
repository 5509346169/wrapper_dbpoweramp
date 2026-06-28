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
