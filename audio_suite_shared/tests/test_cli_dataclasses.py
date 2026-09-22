"""
Tests for audio_suite_shared.cli_dataclasses — validation functions
Gap G-02: validate_folder_path, validate_source_output_paths,
          validate_bpm_range, validate_target_lufs, validate_tempo_scheme
"""

import pytest

from audio_suite_shared.cli_dataclasses import (
    CLIValidationError,
    validate_bpm_range,
    validate_folder_path,
    validate_source_output_paths,
    validate_target_lufs,
    validate_tempo_scheme,
)

# ── CLIValidationError ────────────────────────────────────────────────────────


class TestCLIValidationError:
    def test_is_valueerror_subclass(self):
        assert issubclass(CLIValidationError, ValueError)

    def test_carries_message(self):
        exc = CLIValidationError("Folder path does not exist: /x")
        assert str(exc) == "Folder path does not exist: /x"

    def test_catchable_as_valueerror(self):
        with pytest.raises(ValueError):
            raise CLIValidationError("bad args")


# ── validate_folder_path ──────────────────────────────────────────────────────


class TestValidateFolderPath:
    def test_valid_existing_directory_returns_no_errors(self, tmp_path):
        errors = validate_folder_path(str(tmp_path))
        assert errors == []

    def test_nonexistent_path_returns_error(self):
        errors = validate_folder_path("/no/such/path/xyz_does_not_exist")
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_not_directory_returns_error(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        errors = validate_folder_path(str(f))
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_empty_string_returns_no_errors(self):
        """Empty/None path is treated as 'not provided' — no validation."""
        errors = validate_folder_path("")
        assert errors == []

    def test_none_returns_no_errors(self):
        errors = validate_folder_path(None)
        assert errors == []

    def test_error_message_contains_path(self, tmp_path):
        bad = str(tmp_path / "missing")
        errors = validate_folder_path(bad)
        assert bad in errors[0]

    def test_returns_list(self, tmp_path):
        assert isinstance(validate_folder_path(str(tmp_path)), list)


# ── validate_source_output_paths ─────────────────────────────────────────────


class TestValidateSourceOutputPaths:
    def test_both_valid_returns_no_errors(self, tmp_path):
        src = tmp_path / "source"
        out = tmp_path / "output"
        src.mkdir()
        out.mkdir()
        errors = validate_source_output_paths(str(src), str(out))
        assert errors == []

    def test_missing_source_returns_error(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        errors = validate_source_output_paths("/no/such/source", str(out))
        assert any(
            "source" in e.lower() or "does not exist" in e.lower() for e in errors
        )

    def test_missing_output_returns_error(self, tmp_path):
        src = tmp_path / "source"
        src.mkdir()
        errors = validate_source_output_paths(str(src), "/no/such/output")
        assert any(
            "output" in e.lower() or "does not exist" in e.lower() for e in errors
        )

    def test_both_missing_returns_two_errors(self):
        errors = validate_source_output_paths("/no/src", "/no/out")
        assert len(errors) == 2

    def test_source_is_file_not_dir_returns_error(self, tmp_path):
        f = tmp_path / "file.mp3"
        f.write_bytes(b"x")
        out = tmp_path / "out"
        out.mkdir()
        errors = validate_source_output_paths(str(f), str(out))
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_empty_paths_are_skipped(self):
        """Empty source/output should not be validated (not provided)."""
        errors = validate_source_output_paths("", "")
        assert errors == []

    def test_only_source_empty(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        errors = validate_source_output_paths("", str(out))
        assert errors == []

    def test_returns_list(self, tmp_path):
        assert isinstance(validate_source_output_paths("", ""), list)


# ── validate_bpm_range ────────────────────────────────────────────────────────


class TestValidateBpmRange:
    def test_valid_range_returns_no_errors(self):
        assert validate_bpm_range(60, 180) == []

    def test_minimum_zero_is_valid(self):
        assert validate_bpm_range(0, 1) == []

    def test_maximum_300_is_valid(self):
        assert validate_bpm_range(1, 300) == []

    def test_zero_to_300_full_range_is_valid(self):
        assert validate_bpm_range(0, 300) == []

    def test_min_negative_returns_error(self):
        errors = validate_bpm_range(-1, 180)
        assert len(errors) >= 1
        assert any("minimum" in e.lower() for e in errors)

    def test_min_over_300_returns_error(self):
        errors = validate_bpm_range(301, 302)
        assert any("minimum" in e.lower() for e in errors)

    def test_max_over_300_returns_error(self):
        errors = validate_bpm_range(60, 301)
        assert any("maximum" in e.lower() for e in errors)

    def test_max_negative_returns_error(self):
        errors = validate_bpm_range(0, -1)
        assert len(errors) >= 1

    def test_min_equals_max_returns_error(self):
        errors = validate_bpm_range(120, 120)
        assert len(errors) >= 1
        assert any("less than" in e.lower() or ">=" in e for e in errors)

    def test_min_greater_than_max_returns_error(self):
        errors = validate_bpm_range(180, 60)
        assert len(errors) >= 1

    def test_typical_house_range_is_valid(self):
        assert validate_bpm_range(120, 135) == []

    def test_error_contains_actual_values(self):
        errors = validate_bpm_range(-5, 60)
        assert "-5" in " ".join(errors)

    def test_returns_list(self):
        assert isinstance(validate_bpm_range(60, 120), list)


# ── validate_target_lufs ──────────────────────────────────────────────────────


class TestValidateTargetLufs:
    def test_typical_streaming_target_valid(self):
        assert validate_target_lufs(-14.0) == []

    def test_minus_23_ebu_standard_valid(self):
        assert validate_target_lufs(-23.0) == []

    def test_all_five_presets_valid(self):
        for preset in (-12.0, -14.0, -16.0, -18.0, -23.0):
            assert validate_target_lufs(preset) == []

    def test_zero_returns_error(self):
        errors = validate_target_lufs(0.0)
        assert len(errors) == 1

    def test_minus_70_returns_error(self):
        errors = validate_target_lufs(-70.0)
        assert len(errors) == 1

    def test_positive_value_returns_error(self):
        errors = validate_target_lufs(1.0)
        assert len(errors) == 1
        assert "LUFS" in errors[0]

    def test_non_preset_value_between_presets_returns_error(self):
        # -20.0 sits between -18.0 and -23.0 but is not itself a supported preset
        errors = validate_target_lufs(-20.0)
        assert len(errors) == 1

    def test_far_positive_returns_error(self):
        errors = validate_target_lufs(100.0)
        assert len(errors) == 1

    def test_far_negative_returns_error(self):
        errors = validate_target_lufs(-1000.0)
        assert len(errors) == 1

    def test_error_contains_actual_value(self):
        errors = validate_target_lufs(5.5)
        assert "5.5" in " ".join(errors)

    def test_returns_list(self):
        assert isinstance(validate_target_lufs(-14.0), list)

    @pytest.mark.parametrize("lufs", [-12.0, -14.0, -16.0, -18.0, -23.0])
    def test_supported_presets_valid(self, lufs):
        assert validate_target_lufs(lufs) == []

    @pytest.mark.parametrize("lufs", [-10.0, -5.0, -13.0, -15.5, -20.0, -25.0])
    def test_non_preset_values_return_error(self, lufs):
        assert validate_target_lufs(lufs) != []

    def test_float_precision_tolerance(self):
        # Values within 1e-6 of a preset must pass.
        assert validate_target_lufs(-16.0 + 1e-7) == []
        assert validate_target_lufs(-16.0 - 1e-7) == []

    def test_boundary_just_outside_tolerance_fails(self):
        assert validate_target_lufs(-16.0 + 2e-6) != []

    def test_error_message_lists_all_five_presets(self):
        errors = validate_target_lufs(-15.0)
        for preset in ("-12.0", "-14.0", "-16.0", "-18.0", "-23.0"):
            assert preset in errors[0]


# ── validate_tempo_scheme ─────────────────────────────────────────────────────


class TestValidateTempoScheme:
    VALID_SCHEMES = ["italian", "german", "bpm_only", "hybrid"]

    def test_valid_scheme_returns_no_errors(self):
        for scheme in self.VALID_SCHEMES:
            errors = validate_tempo_scheme(scheme, self.VALID_SCHEMES)
            assert errors == [], f"Expected no errors for scheme '{scheme}'"

    def test_invalid_scheme_returns_error(self):
        errors = validate_tempo_scheme("nonsense", self.VALID_SCHEMES)
        assert len(errors) == 1
        assert "invalid" in errors[0].lower() or "nonsense" in errors[0]

    def test_error_lists_valid_schemes(self):
        errors = validate_tempo_scheme("bad", self.VALID_SCHEMES)
        # At least one valid scheme name should appear in the message
        assert any(s in errors[0] for s in self.VALID_SCHEMES)

    def test_empty_scheme_returns_no_errors(self):
        """Empty string means 'not provided' — skip validation."""
        errors = validate_tempo_scheme("", self.VALID_SCHEMES)
        assert errors == []

    def test_none_scheme_returns_no_errors(self):
        errors = validate_tempo_scheme(None, self.VALID_SCHEMES)
        assert errors == []

    def test_case_sensitive_mismatch_returns_error(self):
        """Schemes are case-sensitive; 'Italian' ≠ 'italian'."""
        errors = validate_tempo_scheme("Italian", self.VALID_SCHEMES)
        assert len(errors) == 1

    def test_empty_valid_schemes_list_any_non_empty_fails(self):
        errors = validate_tempo_scheme("something", [])
        assert len(errors) == 1

    def test_single_scheme_list(self):
        assert validate_tempo_scheme("italian", ["italian"]) == []
        assert validate_tempo_scheme("german", ["italian"]) != []

    def test_returns_list(self):
        assert isinstance(validate_tempo_scheme("x", ["x"]), list)


# ═══════════════════════════════════════════════════════════════════════════════
# Dataclass types
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaseCLIArgs:
    """Tests for the BaseCLIArgs dataclass."""

    def test_defaults(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs

        args = BaseCLIArgs()
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_custom_values(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs

        args = BaseCLIArgs(
            folder_path="/music", live_mode=True, auto_start=True, auto_end=True
        )
        assert args.folder_path == "/music"
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True

    def test_immutable_like_behavior(self) -> None:
        """Dataclass fields are mutable by default — verify assignment works."""
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs

        args = BaseCLIArgs()
        args.folder_path = "/new/path"
        assert args.folder_path == "/new/path"


class TestSourceOutputArgs:
    """Tests for the SourceOutputArgs dataclass."""

    def test_inherits_base_defaults(self) -> None:
        from audio_suite_shared.cli_dataclasses import SourceOutputArgs

        args = SourceOutputArgs()
        assert args.folder_path == ""
        assert args.source == ""
        assert args.output == ""

    def test_custom_values(self) -> None:
        from audio_suite_shared.cli_dataclasses import SourceOutputArgs

        args = SourceOutputArgs(source="/src", output="/out", auto_start=True)
        assert args.source == "/src"
        assert args.output == "/out"
        assert args.auto_start is True

    def test_is_base_cli_args_subclass(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs, SourceOutputArgs

        assert issubclass(SourceOutputArgs, BaseCLIArgs)


class TestBPMArgs:
    """Tests for the BPMArgs dataclass."""

    def test_defaults(self) -> None:
        from audio_suite_shared.cli_dataclasses import BPMArgs

        args = BPMArgs()
        assert args.bpm_min == 75
        assert args.bpm_max == 175
        assert args.duration == 90

    def test_custom_values(self) -> None:
        from audio_suite_shared.cli_dataclasses import BPMArgs

        args = BPMArgs(bpm_min=60, bpm_max=180, duration=120)
        assert args.bpm_min == 60
        assert args.bpm_max == 180
        assert args.duration == 120

    def test_inherits_base(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs, BPMArgs

        assert issubclass(BPMArgs, BaseCLIArgs)


class TestTempoAnalyzerArgs:
    """Tests for the TempoAnalyzerArgs dataclass."""

    def test_default_scheme_is_none(self) -> None:
        from audio_suite_shared.cli_dataclasses import TempoAnalyzerArgs

        args = TempoAnalyzerArgs()
        assert args.scheme is None

    def test_custom_scheme(self) -> None:
        from audio_suite_shared.cli_dataclasses import TempoAnalyzerArgs

        args = TempoAnalyzerArgs(scheme="italian")
        assert args.scheme == "italian"

    def test_inherits_base(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs, TempoAnalyzerArgs

        assert issubclass(TempoAnalyzerArgs, BaseCLIArgs)


class TestReplayGainArgs:
    """Tests for the ReplayGainArgs dataclass."""

    def test_default_target_lufs(self) -> None:
        from audio_suite_shared.cli_dataclasses import ReplayGainArgs

        args = ReplayGainArgs()
        assert args.target_lufs == -16.0

    def test_custom_target_lufs(self) -> None:
        from audio_suite_shared.cli_dataclasses import ReplayGainArgs

        args = ReplayGainArgs(target_lufs=-14.0)
        assert args.target_lufs == -14.0

    def test_inherits_base(self) -> None:
        from audio_suite_shared.cli_dataclasses import BaseCLIArgs, ReplayGainArgs

        assert issubclass(ReplayGainArgs, BaseCLIArgs)


class TestValidTargetLufsValues:
    """Tests for the VALID_TARGET_LUFS_VALUES constant."""

    def test_has_five_presets(self) -> None:
        from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

        assert len(VALID_TARGET_LUFS_VALUES) == 5

    def test_presets_are_all_negative(self) -> None:
        from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

        assert all(v < 0 for v in VALID_TARGET_LUFS_VALUES)

    def test_presets_are_strictly_descending(self) -> None:
        """Presets descend from highest (least negative) to lowest."""
        from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

        for i in range(1, len(VALID_TARGET_LUFS_VALUES)):
            assert VALID_TARGET_LUFS_VALUES[i] < VALID_TARGET_LUFS_VALUES[i - 1]

    @pytest.mark.parametrize("expected", [-12.0, -14.0, -16.0, -18.0, -23.0])
    def test_expected_values_present(self, expected: float) -> None:
        from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES

        assert expected in VALID_TARGET_LUFS_VALUES
