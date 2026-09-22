"""
Tests for music_format_converter.utils.ffmpeg_check
"""

import subprocess
from unittest.mock import MagicMock, patch

from music_format_converter.utils.ffmpeg_check import check_ffmpeg


class TestCheckFfmpeg:
    def test_returns_true_when_ffmpeg_exits_zero(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            return_value=mock_result,
        ):
            assert check_ffmpeg() is True

    def test_returns_false_when_ffmpeg_exits_nonzero(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            return_value=mock_result,
        ):
            assert check_ffmpeg() is False

    def test_returns_false_when_ffmpeg_not_found(self):
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            side_effect=FileNotFoundError("ffmpeg not found"),
        ):
            assert check_ffmpeg() is False

    def test_returns_false_on_timeout(self):
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5),
        ):
            assert check_ffmpeg() is False

    def test_never_raises(self):
        """check_ffmpeg must not propagate any exception."""
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            side_effect=OSError("unexpected OS error"),
        ):
            result = check_ffmpeg()
        assert isinstance(result, bool)

    def test_calls_ffmpeg_version(self):
        """Verify the exact command invoked."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            return_value=mock_result,
        ) as mock_run:
            check_ffmpeg()
        args, _ = mock_run.call_args
        assert args[0] == "ffmpeg"
        assert args[1] == ["-version"]

    def test_returns_bool_not_int(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "music_format_converter.utils.ffmpeg_check.run_secure_subprocess",
            return_value=mock_result,
        ):
            result = check_ffmpeg()
        assert type(result) is bool
