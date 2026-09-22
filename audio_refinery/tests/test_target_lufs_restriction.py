"""
audio_refinery/tests/test_target_lufs_restriction.py
Tests for the Target LUFS preset restriction within Audio Refinery.

Covers:
  - audio_refinery.utils.cli_args.parse()
  - audio_refinery.utils.settings._sanitise_target_lufs()
  - audio_refinery.utils.settings.load()
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import audio_refinery.utils.cli_args as refinery_cli
import audio_refinery.utils.settings as refinery_settings
from audio_refinery.core.models import StageConfig
from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

VALID_LUFS = list(VALID_TARGET_LUFS_VALUES)
INVALID_LUFS = [-10.0, -13.0, -15.5, -20.0, -25.0, 0.0, -70.0, 1.0]


# ── cli_args.parse() ──────────────────────────────────────────────────────────


class TestRefineryCliParse:
    @pytest.mark.parametrize("lufs", VALID_LUFS)
    def test_valid_preset_accepted(self, lufs: float) -> None:
        with patch.object(sys, "argv", ["prog", "--target-lufs", str(lufs)]):
            result = refinery_cli.parse()
        assert result.target_lufs == lufs

    @pytest.mark.parametrize("lufs", INVALID_LUFS)
    def test_invalid_value_raises_system_exit(self, lufs: float) -> None:
        with patch.object(sys, "argv", ["prog", "--target-lufs", str(lufs)]):
            with pytest.raises(SystemExit):
                refinery_cli.parse()

    def test_default_is_valid_preset(self) -> None:
        with patch.object(sys, "argv", ["prog"]):
            result = refinery_cli.parse()
        assert result.target_lufs in VALID_TARGET_LUFS_VALUES


# ── settings._sanitise_target_lufs() ─────────────────────────────────────────


class TestSanitiseTargetLufs:
    @pytest.mark.parametrize("lufs", VALID_LUFS)
    def test_valid_preset_returned_unchanged(self, lufs: float) -> None:
        assert refinery_settings._sanitise_target_lufs(lufs) == lufs

    @pytest.mark.parametrize("lufs", INVALID_LUFS)
    def test_invalid_value_returns_default(self, lufs: float) -> None:
        result = refinery_settings._sanitise_target_lufs(lufs)
        assert result == refinery_settings._DEFAULT_TARGET_LUFS

    @pytest.mark.parametrize("lufs", INVALID_LUFS)
    def test_invalid_value_logs_warning(self, lufs: float, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="audio_refinery.utils.settings"):
            refinery_settings._sanitise_target_lufs(lufs)
        assert caplog.records


# ── settings.load() ───────────────────────────────────────────────────────────


class TestRefinerySettingsLoad:
    def _write_settings(self, tmp_path: Path, target_lufs: float) -> Path:
        data = {
            "declick": True,
            "trim": True,
            "enhance": True,
            "normalise": True,
            "declick_params": {"sensitivity": 0.1, "max_width_ms": 2},
            "trim_params": {
                "threshold": -50,
                "apply_fade": False,
                "fade_in_ms": 500,
                "fade_out_ms": 1000,
            },
            "enhance_params": {
                "preset": "Moderate",
                "noise_gate_threshold_db": -65.0,
                "compressor_threshold_db": -22.0,
                "compressor_ratio": 3.5,
                "compressor_attack_ms": 8.0,
                "compressor_release_ms": 120.0,
                "low_shelf_gain_db": 2.5,
                "low_shelf_freq_hz": 100.0,
                "presence_gain_db": 2.5,
                "presence_freq_hz": 3500.0,
                "high_shelf_gain_db": 4.0,
                "high_shelf_freq_hz": 7000.0,
                "output_gain_db": 0.0,
                "limiter_threshold_db": -0.5,
            },
            "normalise_params": {"target_lufs": target_lufs, "tolerance": 0.5},
        }
        settings_file = tmp_path / "refinery_settings.json"
        settings_file.write_text(json.dumps(data), encoding="utf-8")
        return settings_file

    @pytest.mark.parametrize("lufs", VALID_LUFS)
    def test_valid_stored_lufs_loaded_unchanged(
        self, lufs: float, tmp_path: Path
    ) -> None:
        settings_file = self._write_settings(tmp_path, lufs)
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            config = refinery_settings.load()
        assert config.normalise_params.target_lufs == lufs

    @pytest.mark.parametrize("lufs", INVALID_LUFS)
    def test_invalid_stored_lufs_reset_to_default(
        self, lufs: float, tmp_path: Path
    ) -> None:
        """Regression: previously any float stored in JSON was loaded blindly."""
        settings_file = self._write_settings(tmp_path, lufs)
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            config = refinery_settings.load()
        assert (
            config.normalise_params.target_lufs
            == refinery_settings._DEFAULT_TARGET_LUFS
        )

    def test_missing_settings_file_returns_default_config(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with patch.object(refinery_settings, "_SETTINGS_FILE", missing):
            config = refinery_settings.load()
        assert isinstance(config, StageConfig)
        assert config.normalise_params.target_lufs == -16.0

    def test_corrupt_json_returns_default_config(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "refinery_settings.json"
        settings_file.write_text("this is not valid json", encoding="utf-8")
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            config = refinery_settings.load()
        assert isinstance(config, StageConfig)
        assert config.declick is True

    def test_partial_settings_missing_some_keys(self, tmp_path: Path) -> None:
        data = {"declick": False}
        settings_file = tmp_path / "refinery_settings.json"
        settings_file.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            config = refinery_settings.load()
        assert config.declick is False
        assert config.enhance is True  # default

    def test_load_with_utf8_bom(self, tmp_path: Path) -> None:
        data = json.dumps(
            {
                "declick": True,
                "normalise": True,
                "normalise_params": {"target_lufs": -14.0, "tolerance": 0.5},
            }
        )
        bom_data = b"\xef\xbb\xbf" + data.encode("utf-8")
        settings_file = tmp_path / "refinery_settings.json"
        settings_file.write_bytes(bom_data)
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            config = refinery_settings.load()
        assert config.normalise_params.target_lufs == -14.0


# ── settings.save() ──────────────────────────────────────────────────────────


class TestRefinerySettingsSave:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "refinery_settings.json"
        config = StageConfig()
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            refinery_settings.save(config)
        assert settings_file.exists()

    def test_save_round_trip_preserves_config(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "refinery_settings.json"
        original = StageConfig(
            declick=True,
            trim=False,
            enhance=True,
            normalise=True,
            reduce_noise=True,
        )
        original.declick_params.sensitivity = 0.25
        original.normalise_params.target_lufs = -14.0
        original.enhance_params.preset = "Mild"
        original.noise_reduction_params.reduce_hum = True
        original.noise_reduction_params.hum_frequency = 50
        original.noise_reduction_params.hum_harmonics = 4
        original.noise_reduction_params.hum_quality = 45.0
        original.noise_reduction_params.reduce_broadband = True
        original.noise_reduction_params.noise_start_ms = 100
        original.noise_reduction_params.noise_end_ms = 900
        original.noise_reduction_params.gate_threshold_db = 6.0
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            refinery_settings.save(original)
            loaded = refinery_settings.load()
        assert loaded.declick == original.declick
        assert loaded.trim == original.trim
        assert loaded.enhance == original.enhance
        assert loaded.normalise == original.normalise
        assert loaded.reduce_noise == original.reduce_noise
        assert loaded.declick_params.sensitivity == original.declick_params.sensitivity
        assert (
            loaded.normalise_params.target_lufs == original.normalise_params.target_lufs
        )
        assert loaded.enhance_params.preset == original.enhance_params.preset
        assert (
            loaded.noise_reduction_params.reduce_hum
            == original.noise_reduction_params.reduce_hum
        )
        assert (
            loaded.noise_reduction_params.hum_frequency
            == original.noise_reduction_params.hum_frequency
        )
        assert (
            loaded.noise_reduction_params.hum_harmonics
            == original.noise_reduction_params.hum_harmonics
        )
        assert (
            loaded.noise_reduction_params.hum_quality
            == original.noise_reduction_params.hum_quality
        )
        assert (
            loaded.noise_reduction_params.reduce_broadband
            == original.noise_reduction_params.reduce_broadband
        )
        assert (
            loaded.noise_reduction_params.noise_start_ms
            == original.noise_reduction_params.noise_start_ms
        )
        assert (
            loaded.noise_reduction_params.noise_end_ms
            == original.noise_reduction_params.noise_end_ms
        )
        assert (
            loaded.noise_reduction_params.gate_threshold_db
            == original.noise_reduction_params.gate_threshold_db
        )

    def test_save_rejects_invalid_lufs_on_round_trip(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "refinery_settings.json"
        config = StageConfig()
        config.normalise_params.target_lufs = -13.0  # invalid
        with patch.object(refinery_settings, "_SETTINGS_FILE", settings_file):
            refinery_settings.save(config)
            loaded = refinery_settings.load()
        # load sanitises to default
        assert (
            loaded.normalise_params.target_lufs
            == refinery_settings._DEFAULT_TARGET_LUFS
        )

    def test_save_write_error_logged_not_raised(self, tmp_path: Path) -> None:
        config = StageConfig()
        with (
            patch.object(
                refinery_settings,
                "_SETTINGS_FILE",
                tmp_path / "nonexistent" / "settings.json",
            ),
            patch.object(refinery_settings.logger, "warning") as mock_warn,
        ):
            refinery_settings.save(config)  # must not raise
        assert mock_warn.called


# ── cli_args.parse() — extended ──────────────────────────────────────────────


class TestRefineryCliParseExtended:
    def test_source_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--source", "D:/Music"]):
            result = refinery_cli.parse()
        assert result.source == "D:/Music"

    def test_output_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--output", "D:/Out"]):
            result = refinery_cli.parse()
        assert result.output == "D:/Out"

    def test_auto_start_flag(self) -> None:
        with patch.object(sys, "argv", ["prog", "--auto-start"]):
            result = refinery_cli.parse()
        assert result.auto_start is True

    def test_auto_end_flag(self) -> None:
        with patch.object(sys, "argv", ["prog", "--auto-end"]):
            result = refinery_cli.parse()
        assert result.auto_end is True

    def test_dry_run_flag(self) -> None:
        with patch.object(sys, "argv", ["prog", "--dry"]):
            result = refinery_cli.parse()
        assert result.dry_run is True

    def test_preset_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--preset", "Mild"]):
            result = refinery_cli.parse()
        assert result.preset == "Mild"

    def test_sensitivity_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--sensitivity", "0.15"]):
            result = refinery_cli.parse()
        assert abs(result.sensitivity - 0.15) < 1e-6

    def test_width_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--width", "5"]):
            result = refinery_cli.parse()
        assert result.width == 5

    def test_stages_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--stages", "declick,enhance"]):
            result = refinery_cli.parse()
        assert result.stages == "declick,enhance"

    def test_tolerance_arg(self) -> None:
        with patch.object(sys, "argv", ["prog", "--tolerance", "0.3"]):
            result = refinery_cli.parse()
        assert abs(result.tolerance - 0.3) < 1e-6

    def test_noise_reduction_flags(self) -> None:
        with patch.object(
            sys,
            "argv",
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
            ],
        ):
            result = refinery_cli.parse()
        assert result.reduce_hum is True
        assert result.hum_frequency == 50
        assert result.hum_harmonics == 4
        assert result.hum_quality == 45.0
        assert result.reduce_broadband is True
        assert result.noise_start_ms == 100
        assert result.noise_end_ms == 900
        assert result.gate_threshold_db == 6.0

    def test_noise_reduction_defaults(self) -> None:
        with patch.object(sys, "argv", ["prog"]):
            result = refinery_cli.parse()
        assert result.reduce_hum is False
        assert result.hum_frequency == 60
        assert result.hum_harmonics == 8
        assert result.hum_quality == 30.0
        assert result.reduce_broadband is False
        assert result.noise_start_ms == 0
        assert result.noise_end_ms == 500
        assert result.gate_threshold_db == 3.0

    def test_unknown_args_silently_discarded(self) -> None:
        with patch.object(
            sys, "argv", ["prog", "--unknown-flag", "value", "--source", "D:/M"]
        ):
            result = refinery_cli.parse()
        assert result.source == "D:/M"
