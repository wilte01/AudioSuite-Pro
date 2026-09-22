"""
tests/test_cli_cue.py — tests for the ``audiosuite cue`` command group.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import audio_suite_shared.cue_cli  # noqa: F401  (registers the cue group)
from audio_suite_shared.cli_base import cli

SHEET_TEXT = """\
PERFORMER "Cue Artist"
TITLE "Cue Album"
FILE "Album.flac" FLAC
  TRACK 01 AUDIO
    TITLE "First"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second"
    INDEX 01 03:45:00
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_sheet(tmp_path: Path) -> Path:
    cue = tmp_path / "album.cue"
    cue.write_text(SHEET_TEXT, encoding="utf-8")
    return cue


class TestParse:
    def test_text_output_lists_tracks(self, runner: CliRunner, tmp_path: Path):
        cue = _write_sheet(tmp_path)
        result = runner.invoke(cli, ["cue", "parse", str(cue)])
        assert result.exit_code == 0
        assert "Cue Album" in result.output
        assert "First" in result.output
        assert "03:45:00" in result.output

    def test_json_output_matches_sheet(self, runner: CliRunner, tmp_path: Path):
        cue = _write_sheet(tmp_path)
        result = runner.invoke(cli, ["cue", "parse", str(cue), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Cue Album"
        assert data["files"][0]["tracks"][1]["start_ms"] == 225000

    def test_bad_sheet_raises_click_exception(self, runner: CliRunner, tmp_path: Path):
        cue = tmp_path / "bad.cue"
        cue.write_text("TRACK 01 AUDIO\n", encoding="utf-8")
        result = runner.invoke(cli, ["cue", "parse", str(cue)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_missing_file_rejected(self, runner: CliRunner, tmp_path: Path):
        result = runner.invoke(cli, ["cue", "parse", str(tmp_path / "nope.cue")])
        assert result.exit_code != 0


class TestGenerate:
    def _make_dir(self, tmp_path: Path) -> Path:
        src = tmp_path / "src"
        src.mkdir()
        (src / "01 - Song One.flac").write_bytes(b"fake")
        (src / "02 - Song Two.flac").write_bytes(b"fake")
        (src / "readme.txt").write_text("ignored", encoding="utf-8")
        return src

    def test_directory_generates_album_cue(self, runner: CliRunner, tmp_path: Path):
        src = self._make_dir(tmp_path)
        result = runner.invoke(
            cli, ["cue", "generate", str(src), "--title", "Test Album"]
        )
        assert result.exit_code == 0, result.output
        cue = src / "album.cue"
        assert cue.exists()
        text = cue.read_text(encoding="utf-8")
        assert 'TITLE "Test Album"' in text
        assert 'FILE "01 - Song One.flac" FLAC' in text
        assert "  TRACK 01 AUDIO" in text
        assert '    TITLE "Song One"' in text

    def test_directory_with_no_audio_raises(self, runner: CliRunner, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(cli, ["cue", "generate", str(empty)])
        assert result.exit_code == 1
        assert "No supported audio files" in result.output

    def test_single_file_generates_matching_cue(
        self, runner: CliRunner, tmp_path: Path
    ):
        audio = tmp_path / "t-01.wav"
        audio.write_bytes(b"fake")
        result = runner.invoke(cli, ["cue", "generate", str(audio)])
        assert result.exit_code == 0, result.output
        cue = tmp_path / "t-01.cue"
        assert cue.exists()
        text = cue.read_text(encoding="utf-8")
        assert 'FILE "t-01.wav" WAVE' in text
        assert "  TRACK 01 AUDIO" in text

    def test_custom_output_path(self, runner: CliRunner, tmp_path: Path):
        src = self._make_dir(tmp_path)
        out = tmp_path / "custom.cue"
        result = runner.invoke(cli, ["cue", "generate", str(src), "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()
        assert not (src / "album.cue").exists()


class TestSplit:
    def test_text_output_lists_created_tracks(self, runner: CliRunner, tmp_path: Path):
        cue = _write_sheet(tmp_path)
        with patch(
            "audio_suite_shared.cue_cli.split_cue_file",
            return_value=[str(tmp_path / "01 - First.flac")],
        ) as mock_split:
            result = runner.invoke(cli, ["cue", "split", str(cue)])
        assert result.exit_code == 0
        mock_split.assert_called_once()
        kwargs = mock_split.call_args.kwargs
        assert kwargs["ffmpeg"] == "ffmpeg"
        assert "Split 1 track(s)" in result.output

    def test_json_output(self, runner: CliRunner, tmp_path: Path):
        cue = _write_sheet(tmp_path)
        with patch(
            "audio_suite_shared.cue_cli.split_cue_file",
            return_value=[str(tmp_path / "01 - First.flac")],
        ):
            result = runner.invoke(cli, ["cue", "split", str(cue), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["output_dir"] == str(tmp_path)
        assert len(data["tracks"]) == 1

    def test_error_becomes_click_exception(self, runner: CliRunner, tmp_path: Path):
        cue = _write_sheet(tmp_path)
        with patch(
            "audio_suite_shared.cue_cli.split_cue_file",
            side_effect=ValueError("no INDEX 01"),
        ):
            result = runner.invoke(cli, ["cue", "split", str(cue)])
        assert result.exit_code == 1
        assert "no INDEX 01" in result.output


class TestGroupRegistration:
    def test_cue_group_appears_in_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "cue" in result.output

    def test_cue_group_help_lists_subcommands(self, runner: CliRunner):
        result = runner.invoke(cli, ["cue", "--help"])
        assert result.exit_code == 0
        for sub in ("parse", "generate", "split"):
            assert sub in result.output
