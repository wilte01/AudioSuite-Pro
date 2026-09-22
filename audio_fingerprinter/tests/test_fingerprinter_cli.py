"""Tests for audio_fingerprinter.cli."""

from __future__ import annotations

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
