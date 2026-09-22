"""Tests for audio_suite_shared.cli_app — unified Click CLI."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import _run_tool, cli

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_music_dir(tmp_path: pytest.TempPathFactory) -> str:
    d = tmp_path / "music"
    d.mkdir()
    (d / "track1.mp3").write_bytes(b"fake")
    (d / "track2.flac").write_bytes(b"fake")
    return str(d)


# ── CLI registration ──────────────────────────────────────────────────────────


class TestCliRegistration:
    def test_cli_group_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AudioSuite-Pro" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("audiosuite, version")

    def test_log_level(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--log-level", "DEBUG", "stats", "--help"])
        assert result.exit_code == 0

    def test_unknown_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["nonexistent"])
        assert result.exit_code != 0
        assert "No such command" in result.output


# ── All subcommands: help text and basic parsing ──────────────────────────────


HELP_FLAGS: list[tuple[str, str]] = [
    ("bpm", "Detect and tag BPM"),
    ("key", "Detect and tag musical key"),
    ("tempo", "Derive tempo markings"),
    ("replaygain", "write ReplayGain tags"),
    ("genre-sync", "Sync genre tags"),
    ("normalise", "Normalise audio loudness"),
    ("scrub", "Scrub metadata"),
    ("convert", "Convert audio files"),
    ("silence-trim", "Trim silence"),
    ("declick", "Remove pops and clicks"),
    ("enhance", "Enhance audio"),
    ("stats", "aggregate tag statistics"),
]


class TestSubcommandHelp:
    @pytest.mark.parametrize("command,help_text", HELP_FLAGS)
    def test_subcommand_help(
        self, runner: CliRunner, command: str, help_text: str
    ) -> None:
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0, f"'{command}' --help failed: {result.output}"
        assert help_text.lower() in result.output.lower()

    @pytest.mark.parametrize("command,help_text", HELP_FLAGS)
    def test_subcommand_accepts_directory_argument(
        self,
        runner: CliRunner,
        command: str,
        help_text: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        d = tmp_path / "m"
        d.mkdir()
        # These commands require a directory argument — verify the parser accepts it
        result = runner.invoke(cli, [command, str(d), "--help"])
        assert result.exit_code == 0, (
            f"'{command} <dir> --help' failed: {result.output}"
        )


# ── Dry-run invocations (no actual processing) ────────────────────────────────


class TestDryRunInvocations:
    def test_bpm_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli,
            [
                "bpm",
                temp_music_dir,
                "--dry",
                "--bpm-min",
                "60",
                "--bpm-max",
                "180",
                "--duration",
                "5",
            ],
        )
        # Should complete without error (exit 0 or non-zero depending on mock)
        assert result.exit_code == 0

    def test_key_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["key", temp_music_dir, "--dry", "--duration", "5"])
        assert result.exit_code == 0

    def test_tempo_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["tempo", temp_music_dir, "--dry", "--scheme", "Italian"]
        )
        assert result.exit_code == 0

    def test_replaygain_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["replaygain", temp_music_dir, "--dry", "--target-lufs", "-14"]
        )
        assert result.exit_code == 0

    def test_normalise_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["normalise", temp_music_dir, "--dry"])
        assert result.exit_code == 0

    def test_normalise_json_flag(self, runner: CliRunner, temp_music_dir: str) -> None:
        """--json must emit a JSON summary without failing."""
        result = runner.invoke(cli, ["normalise", temp_music_dir, "--dry", "--json"])
        assert result.exit_code == 0

    def test_scrub_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["scrub", temp_music_dir, "--dry"])
        assert result.exit_code == 0

    def test_declick_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli,
            [
                "declick",
                temp_music_dir,
                "--dry",
                "--sensitivity",
                "0.3",
                "--max-width",
                "5",
            ],
        )
        assert result.exit_code == 0

    def test_silence_trim_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["silence-trim", temp_music_dir, "--dry"])
        assert result.exit_code == 0


# ── convert subcommand ────────────────────────────────────────────────────────


class TestConvert:
    def test_convert_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["convert", temp_music_dir, "--format", "flac", "--dry"]
        )
        assert result.exit_code == 0

    def test_convert_unknown_format(
        self, runner: CliRunner, temp_music_dir: str
    ) -> None:
        result = runner.invoke(
            cli, ["convert", temp_music_dir, "--format", "xyz", "--dry"]
        )
        assert result.exit_code != 0
        assert "Unsupported format" in result.output


# ── enhance subcommand ────────────────────────────────────────────────────────


class TestEnhance:
    def test_enhance_requires_output_dir(
        self, runner: CliRunner, temp_music_dir: str
    ) -> None:
        result = runner.invoke(cli, ["enhance", temp_music_dir])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output

    def test_enhance_unknown_preset(
        self, runner: CliRunner, temp_music_dir: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        out = tmp_path / "out"
        out.mkdir()
        result = runner.invoke(
            cli,
            [
                "enhance",
                temp_music_dir,
                "--output-dir",
                str(out),
                "--preset",
                "Unknown",
            ],
        )
        assert result.exit_code != 0
        assert "Unknown preset" in result.output


# ── stats subcommand ──────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty_dir(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        result = runner.invoke(cli, ["stats", str(d)])
        assert result.exit_code == 0
        assert "Total files scanned" in result.output

    def test_stats_json_flag(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        result = runner.invoke(cli, ["stats", str(d), "--json"])
        assert result.exit_code == 0
        # Output includes a status line on stderr mixed in; extract JSON portion
        import json

        json_start = result.output.index("{")
        data = json.loads(result.output[json_start:])
        assert data["total_files"] == 0
        assert data["scan_path"] == str(d)

    def test_stats_with_audio_files(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "music"
        d.mkdir()
        (d / "a.mp3").write_bytes(b"fake mp3")
        (d / "b.flac").write_bytes(b"fake flac")
        result = runner.invoke(cli, ["stats", str(d)])
        assert result.exit_code == 0
        assert "Total files scanned" in result.output

    def test_stats_non_existent_dir(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["stats", "C:\\nonexistent_path_xyz"])
        assert result.exit_code != 0
        assert "does not exist" in result.output or "Error" in result.output


# ── _run_tool helper ──────────────────────────────────────────────────────────


class TestRunTool:
    def test_run_tool_success(self) -> None:
        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_progress")
            if cb:
                cb(processed=5, total=10)
            cb2 = kwargs.get("on_complete")
            if cb2:
                cb2(
                    total=10,
                    processed=5,
                    skipped=2,
                    errors=1,
                    duration_secs=2.5,
                    log_entries=[],
                )

        result = _run_tool("test", dummy_run, some_arg="value")
        assert result.total == 10
        assert result.processed == 5
        assert result.skipped == 2
        assert result.errors == 1

    def test_run_tool_error_callback(self) -> None:

        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_error")
            if cb:
                cb("Something broke")

        result = _run_tool("test", dummy_run)
        # on_error only prints to stderr; it does not modify result.errors
        assert result.errors == 0

    def test_run_tool_exception(self) -> None:
        def dummy_run(**kwargs: object) -> None:
            raise RuntimeError("catastrophe")

        result = _run_tool("test", dummy_run)
        assert result.errors == -1

    def test_run_tool_json_output(self, runner: CliRunner) -> None:
        import json

        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_complete")
            if cb:
                cb(
                    total=5,
                    processed=3,
                    skipped=1,
                    errors=1,
                    duration_secs=1.0,
                    log_entries=[],
                )

        result = _run_tool("test", dummy_run)
        d = result.to_dict()
        assert d["total"] == 5
        assert d["processed"] == 3
        assert isinstance(d["duration_str"], str)
        # Verify JSON serializable
        json.dumps(d)


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_bpm_max_min_same(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "m"
        d.mkdir()
        result = runner.invoke(
            cli, ["bpm", str(d), "--bpm-min", "120", "--bpm-max", "120", "--dry"]
        )
        # Parser accepts this; runtime may handle it
        assert result.exit_code == 0

    def test_directory_does_not_exist(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["bpm", "C:\\nonexistent"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_directory_is_file(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["bpm", str(f)])
        assert result.exit_code != 0
