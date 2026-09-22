"""
Tests for cd_ripper.core.rip_log.

Coverage strategy
-----------------
- write_log_line appends a timestamped line to the path get_log_path()
  returns, and appends (doesn't overwrite) across multiple calls.
- A write failure (OSError) is swallowed, never raised to the caller --
  logging must never be able to interrupt an in-progress rip.
- All tests use tmp_path and patch get_log_path so the real prefs
  directory is never touched.
"""

import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub audio_suite_shared.error_logger before importing cd_ripper_config.py
# (rip_log imports cd_ripper_config, which imports audio_suite_shared)
# ---------------------------------------------------------------------------
_error_logger_stub = MagicMock()
_error_logger_stub.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("audio_suite_shared", MagicMock())
sys.modules.setdefault("audio_suite_shared.error_logger", _error_logger_stub)


class TestWriteLogLine:
    def test_appends_message_to_log_file(self, tmp_path) -> None:
        from cd_ripper.core.rip_log import write_log_line

        log_file = tmp_path / "cd_ripper.log"
        with patch("cd_ripper.core.rip_log.get_log_path", return_value=str(log_file)):
            write_log_line("first message")

        content = log_file.read_text()
        assert "first message" in content

    def test_multiple_calls_append_rather_than_overwrite(self, tmp_path) -> None:
        from cd_ripper.core.rip_log import write_log_line

        log_file = tmp_path / "cd_ripper.log"
        with patch("cd_ripper.core.rip_log.get_log_path", return_value=str(log_file)):
            write_log_line("line one")
            write_log_line("line two")

        content = log_file.read_text()
        assert "line one" in content
        assert "line two" in content
        assert content.index("line one") < content.index("line two")

    def test_line_includes_a_timestamp(self, tmp_path) -> None:
        from cd_ripper.core.rip_log import write_log_line

        log_file = tmp_path / "cd_ripper.log"
        with patch("cd_ripper.core.rip_log.get_log_path", return_value=str(log_file)):
            write_log_line("timestamped message")

        line = log_file.read_text().strip()
        timestamp_part = line.split("  ", 1)[0]
        # ISO-format timestamps (timespec="seconds") always contain 'T'.
        assert "T" in timestamp_part

    def test_write_failure_is_swallowed_not_raised(self, tmp_path) -> None:
        from cd_ripper.core.rip_log import write_log_line

        log_file = tmp_path / "cd_ripper.log"
        with (
            patch("cd_ripper.core.rip_log.get_log_path", return_value=str(log_file)),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            write_log_line("should not raise")  # must not raise

    def test_creates_file_on_first_write_if_absent(self, tmp_path) -> None:
        from cd_ripper.core.rip_log import write_log_line

        log_file = tmp_path / "does_not_exist_yet.log"
        assert not log_file.exists()

        with patch("cd_ripper.core.rip_log.get_log_path", return_value=str(log_file)):
            write_log_line("creates the file")

        assert log_file.exists()
