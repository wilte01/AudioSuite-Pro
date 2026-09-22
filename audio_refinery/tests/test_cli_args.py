"""Tests for audio_refinery.utils.cli_args."""

from __future__ import annotations

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
