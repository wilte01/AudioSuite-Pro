"""
Tests for audio_suite_shared.launcher.parse_cli_args

Covers:
    - passthrough success (args returned untouched, tool_parse called with no args)
    - SystemExit from tool_parse → process exits 1
    - CLIValidationError from tool_parse → reason on stderr + exit 1
      (regression — ValueError-family exceptions previously escaped uncaught)
    - a refused launch leaves its reason where the Master Driver can read it
      (PLAN_2026-11-03_2.4.3_structure.md D-22)

Changed in 2.4.3: the reason a launch is refused is captured, logged and
recorded for the driver's failure dialog (D-22).
"""

import logging
import sys

import pytest

from audio_suite_shared.cli_dataclasses import CLIValidationError
from audio_suite_shared.launch_failure import (
    read_launch_failure,
    record_launch_failure,
)
from audio_suite_shared.launcher import parse_cli_args


class TestParseCliArgsSuccess:
    def test_returns_tool_parse_result_unchanged(self):
        sentinel = object()
        assert parse_cli_args(lambda: sentinel) is sentinel

    def test_calls_tool_parse_with_no_arguments(self):
        calls = []

        def tool_parse():
            calls.append(1)
            return "args"

        parse_cli_args(tool_parse)
        assert len(calls) == 1


class TestParseCliArgsSystemExit:
    def test_system_exit_is_reraised_as_exit_1(self):
        def tool_parse():
            raise SystemExit(2)

        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(tool_parse)
        assert exc_info.value.code == 1

    def test_nothing_printed_to_stdout(self, capsys):
        def tool_parse():
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            parse_cli_args(tool_parse)
        captured = capsys.readouterr()
        assert captured.out == ""


class TestParseCliArgsValidationErrors:
    """Regression: CLIValidationError (a ValueError) used to escape the
    launcher's except-SystemExit handler and crash the .pyw with a raw
    traceback instead of a clean exit."""

    def test_validation_error_exits_1(self):
        def tool_parse():
            raise CLIValidationError("Folder path does not exist: /x")

        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(tool_parse)
        assert exc_info.value.code == 1

    def test_validation_error_logs_reason(self, caplog):
        def tool_parse():
            raise CLIValidationError("Folder path does not exist: /x")

        with pytest.raises(SystemExit):
            with caplog.at_level(
                logging.ERROR, logger="audio_suite.audio_suite_shared.launcher"
            ):
                parse_cli_args(tool_parse)
        assert "Folder path does not exist: /x" in caplog.text

    def test_logs_the_failure(self, caplog):
        def tool_parse():
            raise CLIValidationError("bad scheme")

        with pytest.raises(SystemExit):
            with caplog.at_level(
                logging.ERROR, logger="audio_suite.audio_suite_shared.launcher"
            ):
                parse_cli_args(tool_parse)
        assert any("bad scheme" in r.message for r in caplog.records)

    def test_generic_valueerror_still_escapes(self):
        """Only CLIValidationError is handled; unexpected ValueErrors must
        propagate so real bugs are not silently converted into exit code 1."""

        def tool_parse():
            raise ValueError("unexpected bug")

        with pytest.raises(ValueError, match="unexpected bug"):
            parse_cli_args(tool_parse)


class TestRefusedLaunchIsExplained:
    """A launcher that exits 1 must leave *why* it refused.

    The tool's message goes to stderr, which a ``pythonw`` parent never shows,
    so the Master Driver's dialog could say only ``Module failed: <name> (exit
    code 1)``.  The reason is now recorded for that dialog and written to the
    tool's own log (D-22).
    """

    def test_stderr_reason_is_recorded_for_the_driver(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["Library_Stats.pyw", "x"])

        def tool_parse():
            print(
                "Library Statistics: Folder path does not exist: /gone",
                file=sys.stderr,
            )
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            parse_cli_args(tool_parse)

        assert (
            read_launch_failure("Library_Stats.pyw")
            == "Library Statistics: Folder path does not exist: /gone"
        )

    def test_reason_reaches_the_tool_log(self, monkeypatch, caplog):
        monkeypatch.setattr(sys, "argv", ["Library_Stats.pyw", "x"])

        def tool_parse():
            print(
                "Library Statistics: Folder path does not exist: /gone",
                file=sys.stderr,
            )
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            with caplog.at_level(
                logging.ERROR, logger="audio_suite.audio_suite_shared.launcher"
            ):
                parse_cli_args(tool_parse)

        assert "Folder path does not exist: /gone" in caplog.text

    def test_successful_parse_clears_an_earlier_reason(self, monkeypatch):
        """A reason from an earlier launch must never explain this one."""
        monkeypatch.setattr(sys, "argv", ["Library_Stats.pyw", "x"])
        record_launch_failure("Library_Stats.pyw", "an older reason")

        parse_cli_args(lambda: "ok")

        assert read_launch_failure("Library_Stats.pyw") == ""

    def test_real_library_stats_parse_records_the_missing_folder(
        self, monkeypatch, tmp_path
    ):
        """The reported defect: a source folder that no longer exists.

        Runs the tool's real parser through the shared launcher, so the record
        is exercised end to end rather than through a stub that prints for it.
        """
        from library_stats.utils import cli_args

        missing = tmp_path / "moved-away"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "Library_Stats.pyw",
                str(missing),
                "--dry",
                "--start",
                "--no-end",
            ],
        )

        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(cli_args.parse)

        assert exc_info.value.code == 1
        reason = read_launch_failure("Library_Stats.pyw")
        assert "Folder path does not exist" in reason
        assert str(missing) in reason


class TestTempoAnalyzerIntegration:
    """End-to-end: tempo_analyzer's parse() raises the shared exception type
    and the shared launcher converts it into a clean exit."""

    def test_tempo_parse_invalid_folder_via_launcher(self):
        from tempo_analyzer.utils.cli_args import parse

        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(lambda: parse(["prog", "/definitely/not/real/xyz"]))
        assert exc_info.value.code == 1

    def test_tempo_parse_invalid_folder_reason_logged(self, caplog):
        from tempo_analyzer.utils.cli_args import parse

        with pytest.raises(SystemExit):
            with caplog.at_level(
                logging.ERROR, logger="audio_suite.audio_suite_shared.launcher"
            ):
                parse_cli_args(lambda: parse(["prog", "/definitely/not/real/xyz"]))
        assert "does not exist" in caplog.text
