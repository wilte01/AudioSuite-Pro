"""
test_cli_args.py
Pytest suite for noise_reduction.utils.cli_args.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from noise_reduction.utils.cli_args import parse, was_launched_from_driver


def _parse(*args: str):
    """Run parse() with the given sys.argv tokens."""
    with patch.object(sys, "argv", ["app.py", *args]):
        return parse()


class TestDefaults:
    def test_no_args_returns_defaults(self):
        ns = _parse()
        assert ns.folder_path is None
        assert ns.live_mode is False
        assert ns.auto_start is False
        assert ns.auto_end is False
        assert ns.reduce_hum is False
        assert ns.hum_frequency == 60
        assert ns.hum_harmonics == 8
        assert ns.hum_quality == pytest.approx(30.0)
        assert ns.reduce_broadband is False
        assert ns.noise_start_ms == 0
        assert ns.noise_end_ms == 500
        assert ns.gate_threshold_db == pytest.approx(3.0)
        assert ns.clear_logs is False
        assert ns.parallel_run is False

    def test_folder_path_positional(self, tmp_path):
        ns = _parse(str(tmp_path))
        assert ns.folder_path == str(tmp_path)


class TestModeFlags:
    def test_live_flag_sets_live_mode(self):
        ns = _parse("--live")
        assert ns.live_mode is True

    def test_dry_flag_sets_dry_mode(self):
        ns = _parse("--dry")
        assert ns.live_mode is False

    def test_live_and_dry_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            _parse("--live", "--dry")


class TestHumArgs:
    def test_reduce_hum_flag(self):
        ns = _parse("--reduce-hum")
        assert ns.reduce_hum is True

    def test_hum_frequency(self):
        ns = _parse("--hum-frequency", "50")
        assert ns.hum_frequency == 50

    def test_hum_frequency_invalid_choice(self):
        with pytest.raises(SystemExit):
            _parse("--hum-frequency", "45")

    def test_hum_harmonics(self):
        ns = _parse("--hum-harmonics", "12")
        assert ns.hum_harmonics == 12

    def test_hum_harmonics_out_of_range(self):
        with pytest.raises(SystemExit):
            _parse("--hum-harmonics", "25")

    def test_hum_quality(self):
        ns = _parse("--hum-quality", "50.0")
        assert ns.hum_quality == pytest.approx(50.0)

    def test_hum_quality_out_of_range(self):
        with pytest.raises(SystemExit):
            _parse("--hum-quality", "200.0")


class TestBroadbandArgs:
    def test_reduce_broadband_flag(self):
        ns = _parse("--reduce-broadband")
        assert ns.reduce_broadband is True

    def test_noise_start(self):
        ns = _parse("--noise-start", "100")
        assert ns.noise_start_ms == 100

    def test_noise_end(self):
        ns = _parse("--noise-end", "1000")
        assert ns.noise_end_ms == 1000

    def test_gate_threshold(self):
        ns = _parse("--gate-threshold", "6.0")
        assert ns.gate_threshold_db == pytest.approx(6.0)


class TestValidation:
    def test_folder_path_invalid(self):
        with pytest.raises(SystemExit):
            _parse("/nonexistent/path/that/does/not/exist_xyz", "--reduce-hum")

    def test_unknown_args_ignored(self, tmp_path):
        ns = _parse(str(tmp_path), "--reduce-hum", "--some-unknown-flag")
        assert ns.reduce_hum is True


class TestDriverHandshake:
    def test_clear_logs_flags(self):
        ns = _parse("--reduce-hum", "--clear-logs")
        assert ns.clear_logs is True

    def test_no_clear_logs_flags(self):
        ns = _parse("--reduce-hum", "--no-clear-logs")
        assert ns.clear_logs is False

    def test_parallel_run_flags(self):
        ns = _parse("--reduce-hum", "--parallel-run")
        assert ns.parallel_run is True

    def test_launched_from_driver(self):
        with patch.object(sys, "argv", ["app.py", "arg"]):
            assert was_launched_from_driver() is True

    def test_not_launched_from_driver(self):
        with patch.object(sys, "argv", ["app.py"]):
            assert was_launched_from_driver() is False
