"""Tests for ``audiosuite spectrogram``.

The command's contract has three parts worth pinning: a dry run writes nothing
(so a Master Driver Dry Run cannot litter a music folder), a live run writes one
readable PNG per audio file, and one undecodable file is reported without
abandoning the rest of the folder.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import cli
from spectral_viewer.tests.audio_fixtures import write_tone_wav


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def music_dir(tmp_path: Path) -> Path:
    """A folder with two short tones and one non-audio file."""
    write_tone_wav(tmp_path / "first.wav", seconds=0.4)
    write_tone_wav(tmp_path / "second.wav", frequency=880.0, seconds=0.4)
    (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")
    return tmp_path


def _invoke(runner: CliRunner, *args: str):
    return runner.invoke(cli, ["spectrogram", *args])


class TestDryRun:
    def test_dry_writes_nothing_and_lists_paths(
        self, runner: CliRunner, music_dir: Path
    ) -> None:
        result = _invoke(runner, str(music_dir), "--dry")

        assert result.exit_code == 0, result.output
        assert "[DRY] would write" in result.output
        assert str(music_dir / "first_spectrogram.png") in result.output
        assert str(music_dir / "second_spectrogram.png") in result.output
        assert list(music_dir.glob("*.png")) == []

    def test_dry_json_reports_planned_images(
        self, runner: CliRunner, music_dir: Path
    ) -> None:
        result = _invoke(runner, str(music_dir), "--dry", "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["tool"] == "spectral_viewer"
        assert payload["processed"] == 2
        assert payload["written"] == 0
        assert payload["dry_run"] is True
        assert [image["status"] for image in payload["images"]] == [
            "planned",
            "planned",
        ]


class TestLiveRun:
    def test_writes_one_png_per_file(self, runner: CliRunner, music_dir: Path) -> None:
        result = _invoke(runner, str(music_dir))

        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        images = sorted(music_dir.glob("*_spectrogram.png"))
        assert [image.name for image in images] == [
            "first_spectrogram.png",
            "second_spectrogram.png",
        ]
        for image in images:
            assert image.stat().st_size > 5000, image
            assert image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_output_dir_receives_the_images(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "images"

        result = _invoke(runner, str(music_dir), "--output-dir", str(target))

        assert result.exit_code == 0, result.output
        assert len(list(target.glob("*_spectrogram.png"))) == 2
        assert list(music_dir.glob("*.png")) == []

    def test_single_file_path(self, runner: CliRunner, music_dir: Path) -> None:
        source = music_dir / "first.wav"

        result = _invoke(runner, str(source))

        assert result.exit_code == 0, result.output
        assert (music_dir / "first_spectrogram.png").exists()
        assert not (music_dir / "second_spectrogram.png").exists()

    def test_window_and_range_options_reach_the_image(
        self, runner: CliRunner, music_dir: Path
    ) -> None:
        result = _invoke(
            runner,
            str(music_dir / "first.wav"),
            "--start",
            "0.1",
            "--end",
            "0.3",
            "--n-fft",
            "1024",
            "--max-freq",
            "4000",
            "--db-range",
            "60",
            "--cmap",
            "gray",
        )

        assert result.exit_code == 0, result.output
        assert (music_dir / "first_spectrogram.png").exists()

    def test_json_summary_counts_written_images(
        self, runner: CliRunner, music_dir: Path
    ) -> None:
        result = _invoke(runner, str(music_dir), "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["written"] == 2
        assert payload["errors"] == 0
        assert payload["duration_secs"] >= 0.0


class TestFailures:
    def test_empty_directory_is_a_clear_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        result = _invoke(runner, str(empty))

        assert result.exit_code == 1
        assert "No supported audio files" in result.output

    def test_one_undecodable_file_does_not_stop_the_batch(
        self, runner: CliRunner, music_dir: Path
    ) -> None:
        # A .mp3 with bytes that are not an MP3: the decoder rejects it, the
        # rest of the folder must still render.
        (music_dir / "broken.mp3").write_bytes(b"not an mp3 at all")

        result = _invoke(runner, str(music_dir), "--json")

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["errors"] == 1
        assert payload["written"] == 2
        assert "broken.mp3" in payload["error_messages"][0]["source"]
        assert (music_dir / "first_spectrogram.png").exists()

    def test_missing_path_is_rejected_by_click(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = _invoke(runner, str(tmp_path / "nope"))

        assert result.exit_code != 0
        assert "does not exist" in result.output.lower()
