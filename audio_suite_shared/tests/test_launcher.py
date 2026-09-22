"""
Tests for audio_suite_shared.launcher.parse_cli_args

Covers:
    - passthrough success (args returned untouched, tool_parse called with no args)
    - SystemExit from tool_parse → process exits 1
    - CLIValidationError from tool_parse → reason on stderr + exit 1
      (regression — ValueError-family exceptions previously escaped uncaught)
"""

import pytest

from audio_suite_shared.cli_dataclasses import CLIValidationError
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
        import logging

        def tool_parse():
            raise CLIValidationError("Folder path does not exist: /x")

        with pytest.raises(SystemExit):
            with caplog.at_level(logging.ERROR, logger="audio_suite_shared.launcher"):
                parse_cli_args(tool_parse)
        assert "Folder path does not exist: /x" in caplog.text

    def test_logs_the_failure(self, caplog):
        import logging

        def tool_parse():
            raise CLIValidationError("bad scheme")

        with pytest.raises(SystemExit):
            with caplog.at_level(logging.ERROR, logger="audio_suite_shared.launcher"):
                parse_cli_args(tool_parse)
        assert any("bad scheme" in r.message for r in caplog.records)

    def test_generic_valueerror_still_escapes(self):
        """Only CLIValidationError is handled; unexpected ValueErrors must
        propagate so real bugs are not silently converted into exit code 1."""

        def tool_parse():
            raise ValueError("unexpected bug")

        with pytest.raises(ValueError, match="unexpected bug"):
            parse_cli_args(tool_parse)


class TestTempoAnalyzerIntegration:
    """End-to-end: tempo_analyzer's parse() raises the shared exception type
    and the shared launcher converts it into a clean exit."""

    def test_tempo_parse_invalid_folder_via_launcher(self):
        from tempo_analyzer.utils.cli_args import parse

        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(lambda: parse(["prog", "/definitely/not/real/xyz"]))
        assert exc_info.value.code == 1

    def test_tempo_parse_invalid_folder_reason_logged(self, caplog):
        import logging

        from tempo_analyzer.utils.cli_args import parse

        with pytest.raises(SystemExit):
            with caplog.at_level(logging.ERROR, logger="audio_suite_shared.launcher"):
                parse_cli_args(lambda: parse(["prog", "/definitely/not/real/xyz"]))
        assert "does not exist" in caplog.text
