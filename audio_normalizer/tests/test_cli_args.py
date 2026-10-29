"""
audio_normalizer/tests/test_cli_args.py
Tests for Audio Normalizer CLI argument parsing and validation.

Covers:
  - validate_args() — target LUFS preset restriction
  - parse()         — CLI entry point enforcement

Changed in 2.1.7: covers ``--tp``/``--lra`` parsing and range validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_normalizer.utils.cli_args import NormalizerArgs, parse, validate_args
from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

VALID_LUFS = list(VALID_TARGET_LUFS_VALUES)
INVALID_LUFS = [-10.0, -13.0, -15.5, -20.0, -25.0, 0.0, -70.0, 1.0]


# ── validate_args ─────────────────────────────────────────────────────────────


class TestNormalizerValidateArgs:
    @pytest.mark.parametrize("lufs", VALID_LUFS)
    def test_valid_preset_accepted(self, lufs: float) -> None:
        args = NormalizerArgs(target_lufs=lufs)
        assert validate_args(args) == []

    @pytest.mark.parametrize("lufs", INVALID_LUFS)
    def test_invalid_value_rejected(self, lufs: float) -> None:
        errors = validate_args(NormalizerArgs(target_lufs=lufs))
        assert any("LUFS" in e for e in errors)

    def test_old_range_minus_30_rejected(self) -> None:
        """Regression: -30.0 was accepted by the old [-70, 0] guard."""
        assert validate_args(NormalizerArgs(target_lufs=-30.0)) != []

    def test_old_range_minus_5_rejected(self) -> None:
        """Regression: -5.0 was accepted by the old [-70, 0] guard."""
        assert validate_args(NormalizerArgs(target_lufs=-5.0)) != []

    def test_tolerance_negative_rejected(self) -> None:
        args = NormalizerArgs(target_lufs=-16.0, tolerance=-0.1)
        errors = validate_args(args)
        assert any("tolerance" in e.lower() for e in errors)

    def test_invalid_mode_rejected(self) -> None:
        args = NormalizerArgs(target_lufs=-16.0, normalization_mode="bogus")
        errors = validate_args(args)
        assert any("normalization_mode" in e for e in errors)

    def test_valid_modes_accepted(self) -> None:
        for mode in ("normalise", "lossless"):
            args = NormalizerArgs(target_lufs=-16.0, normalization_mode=mode)
            assert validate_args(args) == []

    def test_nonexistent_folder_rejected(self, tmp_path: Path) -> None:
        args = NormalizerArgs(
            folder_path=str(tmp_path / "does_not_exist"),
            target_lufs=-16.0,
        )
        errors = validate_args(args)
        assert any("exist" in e.lower() for e in errors)

    def test_file_path_instead_of_folder_rejected(self, tmp_path: Path) -> None:
        file_path = tmp_path / "somefile.txt"
        file_path.write_text("not a directory")
        args = NormalizerArgs(
            folder_path=str(file_path),
            target_lufs=-16.0,
        )
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)


# ── parse() ───────────────────────────────────────────────────────────────────


class TestNormalizerParse:
    @pytest.mark.parametrize("lufs", VALID_LUFS)
    def test_valid_lufs_via_positional_flag(self, lufs: float, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(lufs)])
        assert result.target_lufs == lufs

    def test_invalid_lufs_raises_system_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "-15.0"])

    def test_default_target_lufs_is_valid_preset(self) -> None:
        result = parse(["prog"])
        assert result.target_lufs in VALID_TARGET_LUFS_VALUES
        # D4 (iteration 9): the argparse default must match the GUI default
        # (-14.0), or applying CLI args silently rewrites the GUI's -14.
        assert result.target_lufs == -14.0

    def test_live_flag_sets_live_mode_true(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--live"])
        assert result.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--dry"])
        assert result.live_mode is False

    def test_start_flag_sets_auto_start_true(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--start"])
        assert result.auto_start is True

    def test_no_start_flag_sets_auto_start_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--no-start"])
        assert result.auto_start is False

    def test_end_flag_sets_auto_end_true(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--end"])
        assert result.auto_end is True

    def test_no_end_flag_sets_auto_end_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--no-end"])
        assert result.auto_end is False

    def test_clear_logs_flag_sets_clear_logs_true(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--clear-logs"])
        assert result.clear_logs is True

    def test_no_clear_logs_flag_sets_clear_logs_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--no-clear-logs"])
        assert result.clear_logs is False

    def test_parallel_run_flag_sets_parallel_run_true(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--parallel-run"])
        assert result.parallel_run is True

    def test_no_parallel_run_flag_sets_parallel_run_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--no-parallel-run"])
        assert result.parallel_run is False

    def test_clear_logs_and_parallel_run_default_false(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0])])
        assert result.clear_logs is False
        assert result.parallel_run is False

    def test_tolerance_flag_sets_tolerance(self, tmp_path: Path) -> None:
        result = parse(
            ["prog", str(tmp_path), str(VALID_LUFS[0]), "--tolerance", "1.5"]
        )
        assert result.tolerance == 1.5

    def test_mode_lossless_flag_sets_mode(self, tmp_path: Path) -> None:
        result = parse(
            ["prog", str(tmp_path), str(VALID_LUFS[0]), "--mode", "lossless"]
        )
        assert result.normalization_mode == "lossless"

    def test_mode_normalise_flag_sets_mode(self, tmp_path: Path) -> None:
        result = parse(
            ["prog", str(tmp_path), str(VALID_LUFS[0]), "--mode", "normalise"]
        )
        assert result.normalization_mode == "normalise"

    def test_default_mode_is_normalise(self) -> None:
        result = parse(["prog"])
        assert result.normalization_mode == "normalise"

    def test_invalid_mode_raises_system_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--mode", "bogus"])

    def test_unknown_flag_is_silently_ignored(self, tmp_path: Path) -> None:
        result = parse(["prog", str(tmp_path), str(VALID_LUFS[0]), "--bogus"])
        assert result.target_lufs == VALID_LUFS[0]
        assert result.folder_path == str(tmp_path)

    def test_multiple_flags_combined(self, tmp_path: Path) -> None:
        result = parse(
            [
                "prog",
                str(tmp_path),
                str(VALID_LUFS[0]),
                "--live",
                "--start",
                "--end",
                "--tolerance",
                "0.3",
            ]
        )
        assert result.live_mode is True
        assert result.auto_start is True
        assert result.auto_end is True
        assert result.tolerance == 0.3

    def test_validation_failure_raises_system_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            # Valid path but invalid LUFS value
            parse(["prog", str(tmp_path), "-30.0"])

    def test_non_float_tolerance_ignored(self, tmp_path: Path) -> None:
        """If the value after --tolerance is not parseable as float,
        tolerance should keep its default and parsing continues."""
        result = parse(
            ["prog", str(tmp_path), str(VALID_LUFS[0]), "--tolerance", "not-a-number"]
        )
        assert result.tolerance == 0.5  # default


class TestParseInvalidFolderPath:
    """Regression: parse() used to discard validation errors and exit
    silently with SystemExit(1). Errors must now reach stderr."""

    def test_nonexistent_folder_raises_systemexit(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])

    def test_nonexistent_folder_prints_error_to_stderr(
        self, tmp_path: Path, capsys
    ) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "exist" in captured.err
        assert str(missing) in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(
        self, tmp_path: Path, capsys
    ) -> None:
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_error_message_prefixed_with_tool_name(
        self, tmp_path: Path, capsys
    ) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "Audio Normalizer:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(
        self, tmp_path: Path, capsys
    ) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


class TestDeliveryTargetArgs:
    """F-09: the GUI/Driver argv parser accepts and validates --tp/--lra."""

    def test_defaults_match_the_shipped_targets(self) -> None:
        args = parse(["prog"])
        assert args.true_peak == -1.5
        assert args.lra == 11.0

    def test_tp_and_lra_are_parsed(self, tmp_path: Path) -> None:
        result = parse(
            ["prog", str(tmp_path), str(VALID_LUFS[0]), "--tp", "-1.0", "--lra", "7"]
        )
        assert result.true_peak == -1.0
        assert result.lra == 7.0

    @pytest.mark.parametrize("value", [-10.0, 0.5])
    def test_ceiling_outside_range_is_rejected(self, value: float) -> None:
        errors = validate_args(NormalizerArgs(target_lufs=-16.0, true_peak=value))
        assert any("True-peak ceiling" in e for e in errors)

    @pytest.mark.parametrize("value", [0.5, 21.0])
    def test_lra_outside_range_is_rejected(self, value: float) -> None:
        errors = validate_args(NormalizerArgs(target_lufs=-16.0, lra=value))
        assert any("LRA" in e for e in errors)

    def test_valid_targets_are_accepted(self) -> None:
        args = NormalizerArgs(target_lufs=-16.0, true_peak=-1.0, lra=7.0)
        assert validate_args(args) == []
