"""Tests for audio_refinery.utils.cli_args.

Changed in 2.5.0: album mode is a flag on this surface too, and defaults off
(F-E1).

Changed in 2.5.0: an exact trim range is configured here too, and a range flag
without ``--trim-mode exact`` is refused rather than ignored (F-E3).
"""

from __future__ import annotations

import pytest

from audio_refinery.utils.cli_args import RefineryArgs, parse

# ── WasLaunchedFromDriver ─────────────────────────────────────────────────


class TestDisplayFlags:
    """Tests for clear_logs and parallel_run display-only fields."""

    def test_defaults(self) -> None:
        args = RefineryArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_clear_logs_true(self) -> None:
        args = parse(["prog", "--clear-logs"])
        assert args.clear_logs is True
        assert args.parallel_run is False

    def test_clear_logs_false(self) -> None:
        args = parse(["prog", "--no-clear-logs"])
        assert args.clear_logs is False

    def test_parallel_run_true(self) -> None:
        args = parse(["prog", "--parallel-run"])
        assert args.parallel_run is True
        assert args.clear_logs is False

    def test_parallel_run_false(self) -> None:
        args = parse(["prog", "--no-parallel-run"])
        assert args.parallel_run is False

    def test_both_flags(self) -> None:
        args = parse(["prog", "--clear-logs", "--parallel-run"])
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_clear_logs_wins_over_no(self) -> None:
        args = parse(["prog", "--clear-logs", "--no-clear-logs"])
        assert args.clear_logs is False

    def test_parallel_wins_over_no(self) -> None:
        args = parse(["prog", "--parallel-run", "--no-parallel-run"])
        assert args.parallel_run is False


# ── Existing parse behaviour ──────────────────────────────────────────────


class TestParse:
    """Tests for the existing parse function with new fields."""

    def test_defaults(self) -> None:
        args = parse([])
        assert args.source == ""
        assert args.output == ""
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.dry_run is False
        assert args.stages == "declick,trim,enhance,normalise"
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_source(self) -> None:
        args = parse(["prog", "--source", "/music"])
        assert args.source == "/music"

    def test_auto_start_end(self) -> None:
        args = parse(["prog", "--auto-start", "--auto-end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_dry_run(self) -> None:
        args = parse(["prog", "--dry"])
        assert args.dry_run is True

    def test_stages(self) -> None:
        args = parse(["prog", "--stages", "declick,enhance"])
        assert args.stages == "declick,enhance"

    def test_noise_reduction_defaults(self) -> None:
        args = parse([])
        assert args.reduce_hum is False
        assert args.hum_frequency == 60
        assert args.hum_harmonics == 8
        assert args.hum_quality == 30.0
        assert args.reduce_broadband is False
        assert args.noise_start_ms == 0
        assert args.noise_end_ms == 500
        assert args.gate_threshold_db == 3.0

    def test_noise_reduction_flags_parsed(self) -> None:
        args = parse(
            [
                "prog",
                "--reduce-hum",
                "--hum-frequency",
                "50",
                "--hum-harmonics",
                "4",
                "--hum-quality",
                "45.0",
                "--reduce-broadband",
                "--noise-start",
                "100",
                "--noise-end",
                "900",
                "--gate-threshold",
                "6.0",
            ]
        )
        assert args.reduce_hum is True
        assert args.hum_frequency == 50
        assert args.hum_harmonics == 4
        assert args.hum_quality == 45.0
        assert args.reduce_broadband is True
        assert args.noise_start_ms == 100
        assert args.noise_end_ms == 900
        assert args.gate_threshold_db == 6.0

    def test_all_flags_combined(self) -> None:
        args = parse(
            [
                "prog",
                "--source",
                "/music",
                "--auto-start",
                "--auto-end",
                "--dry",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.source == "/music"
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.dry_run is True
        assert args.clear_logs is True
        assert args.parallel_run is True


class TestExactTrimArgs:
    """The five exact-trim options, and the combinations that are refused."""

    def test_defaults_are_silence_trimming(self) -> None:
        args = parse(["prog"])
        assert args.trim_mode == "silence"
        assert args.trim_start is None
        assert args.trim_end is None
        assert args.trim_duration is None
        assert args.trim_copy is False
        assert RefineryArgs().trim_mode == "silence"

    def test_an_exact_range_parses(self) -> None:
        args = parse(
            [
                "prog",
                "--trim-mode",
                "exact",
                "--trim-start",
                "250",
                "--trim-end",
                "750",
                "--trim-copy",
            ]
        )
        assert args.trim_mode == "exact"
        assert args.trim_start == 250
        assert args.trim_end == 750
        assert args.trim_copy is True

    def test_a_duration_replaces_the_end(self) -> None:
        args = parse(["prog", "--trim-mode", "exact", "--trim-duration", "750"])
        assert args.trim_duration == 750
        assert args.trim_end is None

    def test_a_range_flag_without_the_mode_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", "--trim-start", "250"])

    def test_copy_without_the_mode_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", "--trim-copy"])

    def test_exact_without_a_range_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", "--trim-mode", "exact"])

    def test_an_end_and_a_duration_together_are_refused(self) -> None:
        with pytest.raises(SystemExit):
            parse(
                [
                    "prog",
                    "--trim-mode",
                    "exact",
                    "--trim-end",
                    "750",
                    "--trim-duration",
                    "500",
                ]
            )

    def test_a_negative_start_is_refused(self) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", "--trim-mode", "exact", "--trim-start", "-5"])

    def test_no_trim_copy_turns_the_flag_off(self) -> None:
        args = parse(
            [
                "prog",
                "--trim-mode",
                "exact",
                "--trim-end",
                "750",
                "--trim-copy",
                "--no-trim-copy",
            ]
        )
        assert args.trim_copy is False


class TestAlbumMode:
    """The flag the Master Driver emits, and the default that keeps runs unchanged."""

    def test_album_mode_defaults_off(self) -> None:
        assert parse(["prog"]).album_mode is False
        assert RefineryArgs().album_mode is False

    def test_album_mode_flag_reaches_the_args(self) -> None:
        assert parse(["prog", "--album-mode"]).album_mode is True

    def test_no_album_mode_turns_it_off_again(self) -> None:
        assert parse(["prog", "--album-mode", "--no-album-mode"]).album_mode is False
