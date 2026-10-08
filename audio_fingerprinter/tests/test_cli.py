"""Tests for audio_fingerprinter.cli."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from audio_fingerprinter.cli import fingerprint


class TestFingerprintCommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, ["--help"])
        assert result.exit_code == 0
        assert "Chromaprint" in result.output or "fingerprint" in result.output.lower()

    def test_no_directory_shows_usage(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, [])
        assert result.exit_code == 0 or "Usage" in result.output

    def test_nonexistent_directory(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, ["--dir", "/nonexistent/path_12345"])
        assert (
            result.exit_code != 0
            or "does not exist" in result.output.lower()
            or "error" in result.output.lower()
        )


class TestAlbumModeFlags:
    """--album-mode / --album-min must reach FingerprintParams."""

    def _invoke(self, args: list[str]):
        runner = CliRunner()
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
        )
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        params = mock_tool.call_args.kwargs.get("params") if mock_tool.called else None
        return result, params

    def test_album_mode_off_by_default(self, tmp_path):
        result, params = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        assert params.album_mode is False
        assert params.album_min == 3

    def test_album_mode_flag_sets_params(self, tmp_path):
        result, params = self._invoke(
            [str(tmp_path), "--album-mode", "--album-min", "2"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.album_mode is True
        assert params.album_min == 2

    def test_album_min_must_be_at_least_one(self, tmp_path):
        runner = CliRunner()
        with patch("audio_fingerprinter.cli._run_tool"):
            result = runner.invoke(
                fingerprint,
                [str(tmp_path), "--album-mode", "--album-min", "0"],
            )
        assert result.exit_code != 0


class TestMbidFlags:
    """--write-mbids / --mbid-region must reach FingerprintParams, and the
    opt-in must refuse to run without the AcoustID tag write it extends."""

    def _invoke(self, args: list[str]):
        runner = CliRunner()
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
        )
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        params = mock_tool.call_args.kwargs.get("params") if mock_tool.called else None
        return result, params

    def test_write_mbids_off_by_default(self, tmp_path):
        result, params = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is False
        assert params.mbid_region == ""

    def test_write_mbids_flag_sets_params(self, tmp_path):
        result, params = self._invoke(
            [
                str(tmp_path),
                "--write-tags",
                "--write-mbids",
                "--mbid-region",
                "gb",
            ]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is True
        # Region is normalised to the ISO code's canonical upper case.
        assert params.mbid_region == "GB"

    def test_write_mbids_requires_write_tags(self, tmp_path):
        result, _params = self._invoke([str(tmp_path), "--write-mbids"])
        assert result.exit_code == 1
        assert "--write-tags" in result.output

    def test_no_write_mbids_flag(self, tmp_path):
        result, params = self._invoke(
            [str(tmp_path), "--write-tags", "--no-write-mbids"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is False
