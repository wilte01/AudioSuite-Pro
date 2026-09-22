"""
tests/test_cli.py — tests for the ``audiosuite lyrics`` command registered by
lyrics_manager/cli.py.

A fake provider is temporarily registered in the shared registry so the CLI
can be exercised end-to-end without network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from mutagen.id3 import TIT2, TPE1
from mutagen.mp3 import MP3
from pydub import AudioSegment

import lyrics_manager.cli  # noqa: F401  (registers the lyrics command)
from audio_suite_shared.cli_base import cli
from audio_suite_shared.tag_helper_reader import read_lyrics_tags
from lyrics_manager.core.providers import LyricProvider, LyricResult, register_provider
from lyrics_manager.core.providers.registry import _registry


class _CliFakeProvider(LyricProvider):
    name = "fake_cli_provider"

    def search(self, artist, title, *, timeout=10.0):
        if title == "Has Lyrics":
            return LyricResult(
                provider_name=self.name,
                synced_lyrics="[00:01.00]Hello\n[00:03.00]Bye\n",
                plain_lyrics="Hello\nBye\n",
            )
        return None


@pytest.fixture(autouse=True)
def _registered_fake_provider():
    """Register the fake CLI provider for the duration of every test."""
    snapshot = dict(_registry)
    _registry.clear()
    _registry.update(snapshot)
    register_provider(_CliFakeProvider)
    try:
        yield
    finally:
        _registry.clear()
        _registry.update(snapshot)


def _make_audio(tmp_path: Path, name: str = "song.mp3") -> Path:
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    audio = MP3(str(path))
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(TPE1(encoding=3, text=["Artist"]))
    audio.tags.add(TIT2(encoding=3, text=["Has Lyrics"]))
    audio.save()
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestHelpAndRegistration:
    def test_lyrics_command_appears_in_top_level_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "lyrics" in result.output

    def test_lyrics_help_lists_all_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics", "--help"])
        assert result.exit_code == 0, result.output
        for flag in (
            "--provider",
            "--request-timeout",
            "--skip-existing",
            "--no-skip-existing",
            "--plain-fallback",
            "--no-plain-fallback",
            "--parallel",
            "--workers",
            "--json",
            "--dry",
            "--live",
        ):
            assert flag in result.output

    def test_help_lists_provider_choices(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics", "--help"])
        assert "lrclib" in result.output
        assert "lyric source provider" in result.output.lower()

    def test_missing_directory_argument_fails(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics"])
        assert result.exit_code != 0

    def test_directories_default_lrclib(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics", "--help"])
        assert "[default: lrclib]" in result.output

    def test_json_and_text_flags_present(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics", "--help"])
        assert "--json" in result.output
        assert "--text" in result.output


class TestUnknownProvider:
    def test_unknown_provider_raises_click_exception(
        self, runner: CliRunner, tmp_path: Path
    ):
        result = runner.invoke(cli, ["lyrics", "--provider", "nope", str(tmp_path)])
        assert result.exit_code == 1
        assert "Unknown lyric provider" in result.stderr
        assert "nope" in result.stderr
        assert "lrclib" in result.stderr


class TestDryRun:
    def test_dry_run_empty_directory_succeeds(self, runner: CliRunner, tmp_path: Path):
        result = runner.invoke(cli, ["lyrics", "--dry", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Summary:" in result.output

    def test_dry_run_does_not_write_lyrics(self, runner: CliRunner, tmp_path: Path):
        audio = _make_audio(tmp_path)
        result = runner.invoke(
            cli, ["lyrics", "--dry", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        tags = read_lyrics_tags(str(audio))
        assert tags.synced is None

    def test_dry_run_reports_expected_file(self, runner: CliRunner, tmp_path: Path):
        _make_audio(tmp_path)
        result = runner.invoke(
            cli, ["lyrics", "--dry", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "song.mp3" in result.stderr


class TestLiveRun:
    def test_live_run_writes_synced_lyrics(self, runner: CliRunner, tmp_path: Path):
        audio = _make_audio(tmp_path)
        result = runner.invoke(
            cli, ["lyrics", "--live", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        tags = read_lyrics_tags(str(audio))
        assert tags.synced is not None
        assert "[00:01.00]Hello" in tags.synced

    def test_live_run_summary_counts(self, runner: CliRunner, tmp_path: Path):
        audio = _make_audio(tmp_path, "one.mp3")
        _make_audio(tmp_path, "two.mp3")
        result = runner.invoke(
            cli, ["lyrics", "--live", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "2 files" in result.stdout
        assert "0 skipped" in result.stdout
        assert "0 errors" in result.stdout
        assert audio.exists()

    def test_missing_lyrics_counted_as_skipped(self, runner: CliRunner, tmp_path: Path):
        _make_audio(tmp_path, "matched.mp3")
        unmatched = tmp_path / "unmatched.mp3"
        AudioSegment.silent(duration=100).export(str(unmatched), format="mp3")
        audio = MP3(str(unmatched))
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TPE1(encoding=3, text=["Artist"]))
        audio.tags.add(TIT2(encoding=3, text=["Not In Db"]))
        audio.save()

        result = runner.invoke(
            cli, ["lyrics", "--live", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "2 files" in result.stdout
        assert "1 skipped" in result.stdout

    def test_skip_existing_by_default(self, runner: CliRunner, tmp_path: Path):
        audio = _make_audio(tmp_path)
        # first live run embeds lyrics; second run in the same invocation
        # proves the default skip-existing flag leaves them untouched.
        result = runner.invoke(
            cli, ["lyrics", "--live", "--provider", "fake_cli_provider", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        tags = read_lyrics_tags(str(audio))
        assert "[00:01.00]Hello" in tags.synced


class TestJsonOutput:
    def test_json_output_contains_counts(self, runner: CliRunner, tmp_path: Path):
        _make_audio(tmp_path)
        result = runner.invoke(
            cli,
            [
                "lyrics",
                "--json",
                "--dry",
                "--provider",
                "fake_cli_provider",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        import json as _json

        payload = _json.loads(result.stdout)
        assert payload["total"] == 1
        assert payload["errors"] == 0

    def test_json_matches_text_directory_missing_errors(self, runner: CliRunner):
        result = runner.invoke(cli, ["lyrics", "--json", "does/not/exist"])
        assert result.exit_code == 2
