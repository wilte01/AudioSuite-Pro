"""
Tests for cli_helpers module.

Comprehensive test coverage for CLI argument parsing and handlers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    HANDSHAKE_FLAG_PAIRS,
    SourceOutputCLIHandler,
    StandardCLIHandler,
    UniversalCLIHandler,
    apply_handshake_segment,
    consume_handshake_token,
    create_standard_parser,
    parse_cli_args,
    print_tool_usage_error,
    validate_cli_args,
    was_launched_from_driver,
)


class TestCreateStandardParser:
    """Tests for create_standard_parser function."""

    def test_parser_creation(self) -> None:
        """Test parser is created with correct description."""
        parser = create_standard_parser("Test Description", add_stages=True)
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_standard_arguments(self) -> None:
        """Test parser includes standard arguments."""
        parser = create_standard_parser("Test", add_stages=False)
        args = parser.parse_args(["--source", "/tmp", "--output", "/out"])
        assert args.source == "/tmp"
        assert args.output == "/out"

    def test_parser_has_auto_flags(self) -> None:
        """Test parser includes auto-start and auto-end flags."""
        parser = create_standard_parser("Test", add_stages=False)
        args = parser.parse_args(["--auto-start", "--auto-end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_parser_with_stages(self) -> None:
        """Test parser includes stage-related arguments."""
        parser = create_standard_parser("Test", add_stages=True)
        args = parser.parse_args(
            [
                "--stages",
                "declick,trim",
                "--sensitivity",
                "5.5",
                "--target-lufs",
                "-14.0",
            ]
        )
        assert args.stages == "declick,trim"
        assert args.sensitivity == 5.5
        assert args.target_lufs == -14.0

    def test_parser_without_stages(self) -> None:
        """Test parser excludes stage arguments when add_stages=False."""
        parser = create_standard_parser("Test", add_stages=False)
        args = parser.parse_args([])
        assert not hasattr(args, "stages")


class TestWasLaunchedFromDriver:
    """Union matrix of every per-tool test across the 19 Audio Suite apps.

    The canonical function inspects the FULL argv (index 0 = program name)
    and reports True iff more than one entry is present: the Master Driver
    always launches with arguments (path or numeric placeholder, plus the
    display-only handshake flags), while a standalone launch has none.
    """

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(
                [],
                id="empty - album_art_normalizer/album_art_sync/"
                "asx_extractor/key_detector/mood_analyzer/music_format_converter/"
                "mood_analysis_batch_tagger/pop_click_remover/tempo_analyzer",
            ),
            pytest.param(
                ["prog"],
                id="bare - album_genre_tagger/audio_fingerprinter/"
                "bpm_analyzer/genre_sync/lyrics_manager",
            ),
            pytest.param(
                ["script.py"],
                id="bare - album_art_normalizer/album_art_sync/"
                "asx_extractor/key_detector/mood_analyzer/music_format_converter/"
                "mood_analysis_batch_tagger/tempo_analyzer",
            ),
            pytest.param(["app.py"], id="bare - pop_click_remover/noise_reduction"),
            pytest.param(
                ["ReplayGain_Analyzer.pyw"], id="bare launcher - replaygain_analyzer"
            ),
            pytest.param(
                ["Metadata_Scrubber.pyw"], id="bare launcher - metadata_scrubber"
            ),
            pytest.param(["Audio_Refinery.pyw"], id="bare launcher - audio_refinery"),
            pytest.param(["program"], id="bare keyword - audio_refinery"),
        ],
    )
    def test_false_without_arguments(self, argv: list[str]) -> None:
        """A standalone start carries no CLI arguments."""
        assert was_launched_from_driver(argv) is False

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(
                ["script.py", "C:/music"],
                id="path - album_art_normalizer/"
                "album_art_sync/asx_extractor/key_detector/mood_analyzer/"
                "music_format_converter/mood_analysis_batch_tagger/tempo_analyzer",
            ),
            pytest.param(
                ["prog", "--no-clear-logs"],
                id="flag only - genre_tagger/bpm/genre_sync/lyrics_manager",
            ),
            pytest.param(
                ["prog", "D:/Music", "-16.0"],
                id="path+param - replaygain_analyzer",
            ),
            pytest.param(
                ["prog", "--start", "--end"],
                id="flags - replaygain_analyzer/metadata_scrubber",
            ),
            pytest.param(["app.py", "/music"], id="path - pop_click_remover"),
            pytest.param(
                ["app.py", "/music", "--live"], id="path+live - pop_click_remover"
            ),
            pytest.param(["app.py", "arg"], id="single arg - noise_reduction"),
            pytest.param(["prog", "folder"], id="folder - audio_fingerprinter"),
            pytest.param(
                ["Metadata_Scrubber.pyw", "D:/Music"],
                id="launcher+path - metadata_scrubber",
            ),
            pytest.param(
                ["Audio_Refinery.pyw", "--source", "/music"],
                id="launcher+flag - audio_refinery",
            ),
            pytest.param(["program", "--dry"], id="keyword+flag - audio_refinery"),
            pytest.param(
                ["prog", "D:/Music"], id="path - metadata_scrubber/replaygain_analyzer"
            ),
        ],
    )
    def test_true_with_arguments(self, argv: list[str]) -> None:
        """A driver launch always passes at least one CLI argument."""
        assert was_launched_from_driver(argv) is True

    def test_any_argument_means_driven(self, tmp_path: Path) -> None:
        """Path-valued arguments must be detected (album_genre_tagger, bpm_analyzer,
        genre_sync, lyrics_manager)."""
        assert was_launched_from_driver(["prog", str(tmp_path)]) is True

    def test_defaults_to_sys_argv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With argv omitted the full sys.argv vector is inspected."""
        monkeypatch.setattr(sys, "argv", ["prog"])
        assert was_launched_from_driver() is False
        monkeypatch.setattr(sys, "argv", ["prog", "D:/Music"])
        assert was_launched_from_driver() is True


class TestStandardCLIHandler:
    """Tests for StandardCLIHandler class."""

    def test_initialization(self) -> None:
        """Test handler initializes with app instance."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)
        assert handler.app == mock_app

    def test_apply_source_output_args(self) -> None:
        """Test source and output arguments are applied."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()

        args = argparse.Namespace(
            source="/source/dir", output="/output/dir", auto_end=True
        )

        handler.apply_source_output_args(args, mock_source_var, mock_output_var)

        mock_source_var.set.assert_called_once_with("/source/dir")
        mock_output_var.set.assert_called_once_with("/output/dir")

    def test_apply_source_output_args_sets_auto_end(self) -> None:
        """When auto_end_var is supplied, the app's auto_end flag must be
        set from the parsed argument."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()
        mock_auto_end = MagicMock()

        args = argparse.Namespace(
            source="/source/dir", output="/output/dir", auto_end=True
        )

        handler.apply_source_output_args(
            args,
            mock_source_var,
            mock_output_var,
            auto_end_var=mock_auto_end,
        )

        assert mock_app.auto_end is True

    def test_apply_source_output_args_loads_registry(self) -> None:
        """When the app exposes _load_registry it must be called with the
        source directory."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        args = argparse.Namespace(source="/source/dir", output="", auto_end=False)
        handler.apply_source_output_args(
            args, MagicMock(), MagicMock(), auto_end_var=MagicMock()
        )
        mock_app._load_registry.assert_called_once_with("/source/dir")

    def test_apply_stage_args_applies_parameters(self) -> None:
        """Stage parameters must be copied onto the config when matching
        sections and attributes exist."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        config = MagicMock()
        config.declick_params = MagicMock()
        config.trim_params = MagicMock()
        config.enhance_params = MagicMock()
        config.normalise_params = MagicMock()

        args = argparse.Namespace(
            stages="declick",
            sensitivity=7.5,
            width=3.0,
            threshold=-20.0,
            fade=True,
            fade_in=50,
            fade_out=200,
            preset="Custom",
            target_lufs=-23.0,
            tolerance=2.0,
        )

        handler.apply_stage_args(args, config)

        assert config.declick_params.sensitivity == 7.5
        assert config.declick_params.max_width_ms == 3.0
        assert config.trim_params.threshold == -20.0
        assert config.trim_params.apply_fade is True
        assert config.trim_params.fade_in_ms == 50
        assert config.trim_params.fade_out_ms == 200
        assert config.enhance_params.preset == "Custom"
        assert config.normalise_params.target_lufs == -23.0
        assert config.normalise_params.tolerance == 2.0

    def test_apply_source_output_args_with_auto_start(self) -> None:
        """Test that auto-start flag is returned."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()
        mock_auto_start = MagicMock()

        args = argparse.Namespace(
            source="/source", output="/output", auto_end=False, auto_start=True
        )

        result = handler.apply_source_output_args(
            args, mock_source_var, mock_output_var, auto_start_func=mock_auto_start
        )

        assert result is True

    def test_apply_stage_args_no_stages_attribute(self) -> None:
        """Test stage args handling when stages not in args."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        args = argparse.Namespace()  # No stages attribute
        config = MagicMock()

        # Should not raise
        handler.apply_stage_args(args, config)

    def test_apply_stage_args_with_stages(self) -> None:
        """Test stage arguments are applied correctly."""
        mock_app = MagicMock()
        handler = StandardCLIHandler(mock_app)

        args = argparse.Namespace(stages="declick,trim,enhance")
        config = MagicMock()
        config.declick = False
        config.trim = False
        config.enhance = False

        handler.apply_stage_args(args, config)

        assert config.declick is True
        assert config.trim is True
        assert config.enhance is True


class TestSourceOutputCLIHandler:
    """Tests for SourceOutputCLIHandler class."""

    def test_apply_basic_args_delegates_to_parent(self) -> None:
        """Test apply_basic_args delegates to parent method."""
        mock_app = MagicMock()
        handler = SourceOutputCLIHandler(mock_app)

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()

        args = argparse.Namespace(
            source="/source", output="/output", auto_end=False, auto_start=False
        )

        with patch.object(
            StandardCLIHandler, "apply_source_output_args"
        ) as mock_parent:
            handler.apply_basic_args(args, mock_source_var, mock_output_var)
            mock_parent.assert_called_once()


class TestParseCliArgs:
    """Tests for parse_cli_args function."""

    def test_parse_returns_namespace(self) -> None:
        """Test function returns argparse Namespace."""
        with patch("sys.argv", ["test"]):
            result = parse_cli_args("Test Description", add_stages=False)
            assert isinstance(result, argparse.Namespace)


# ---------------------------------------------------------------------------
# Master-Driver display-flag handshake seam (iteration-7 B1)
# ---------------------------------------------------------------------------
# The shared owner of the 10-token handshake ladder. The golden table below is
# transcribed from the pre-refactor per-tool ladders (captured 2026-09-30, see
# PLAN_iteration7_remediation.md item B1): every payload asserts the
# pre-change ladder semantics — five pairs, on/off spellings, one-occurrence
# last-owns consumption — against a BaseCLIArgs-shaped holder.


class _GoldenArgs(BaseCLIArgs):
    """BaseCLIArgs-shaped holder mirroring the per-tool Clear/Parallel fields."""

    clear_logs: bool = False  # Display only - driver-owned orchestration flag
    parallel_run: bool = False  # Display only - driver-owned orchestration flag


def _holder() -> _GoldenArgs:
    return _GoldenArgs(folder_path="D:/Music")


class TestHandshakeFlagContract:
    """The ten shared tokens and exactly two spellings per pair."""

    def test_five_pairs_of_exactly_ten_tokens(self) -> None:
        flags = {pair[0] for pair in HANDSHAKE_FLAG_PAIRS} | {
            pair[1] for pair in HANDSHAKE_FLAG_PAIRS
        }
        assert len(flags) == 10

    def test_pairs_are_on_off_complements(self) -> None:
        positives = {pair[0] for pair in HANDSHAKE_FLAG_PAIRS}
        negatives = {pair[1] for pair in HANDSHAKE_FLAG_PAIRS}
        assert positives == {
            "--live",
            "--start",
            "--end",
            "--clear-logs",
            "--parallel-run",
        }
        assert negatives == {
            "--dry",
            "--no-start",
            "--no-end",
            "--no-clear-logs",
            "--no-parallel-run",
        }


class TestConsumeHandshakeToken:
    """Token-level contract: sets the matched field, rejects others."""

    @pytest.mark.parametrize(
        "token,field,value",
        [
            ("--live", "live_mode", True),
            ("--dry", "live_mode", False),
            ("--start", "auto_start", True),
            ("--no-start", "auto_start", False),
            ("--end", "auto_end", True),
            ("--no-end", "auto_end", False),
            ("--clear-logs", "clear_logs", True),
            ("--no-clear-logs", "clear_logs", False),
            ("--parallel-run", "parallel_run", True),
            ("--no-parallel-run", "parallel_run", False),
        ],
    )
    def test_each_token_maps_its_field(
        self, token: str, field: str, value: bool
    ) -> None:
        args = _holder()
        assert consume_handshake_token(token, args) is True
        assert getattr(args, field) is value

    def test_unrelated_token_is_none(self) -> None:
        args = _holder()
        assert consume_handshake_token("--scheme", args) is None
        assert consume_handshake_token("--duration", args) is None
        assert args == _holder()

    def test_rejected_pair_token_is_false_and_writes_nothing(self) -> None:
        args = _holder()
        accepted = frozenset({"--start"})  # fingerprinter/converter-shaped subset
        assert consume_handshake_token("--no-start", args, accepted=accepted) is False
        assert args.auto_start is False  # untouched default
        assert consume_handshake_token("--start", args, accepted=accepted) is True
        assert args.auto_start is True

    def test_last_occurrence_wins_in_scan_order(self) -> None:
        args = _holder()
        assert consume_handshake_token("--live", args) is True
        assert consume_handshake_token("--dry", args) is True
        assert args.live_mode is False
        args2 = _holder()
        assert consume_handshake_token("--dry", args2) is True
        assert consume_handshake_token("--live", args2) is True
        assert args2.live_mode is True


class TestApplyHandshakeSegment:
    """The segment walk mirrors the pre-change ladder on full token tails."""

    def test_full_driver_tail_all_pairs_applied(self) -> None:
        args = _holder()
        tail = [
            "--live",
            "--start",
            "--end",
            "--clear-logs",
            "--parallel-run",
        ]
        assert apply_handshake_segment(tail, args) is True
        assert (args.live_mode, args.auto_start, args.auto_end) == (True, True, True)
        assert (args.clear_logs, args.parallel_run) == (True, True)

    def test_full_dry_driver_tail(self) -> None:
        args = _holder()
        tail = [
            "--dry",
            "--no-start",
            "--no-end",
            "--no-clear-logs",
            "--no-parallel-run",
        ]
        assert apply_handshake_segment(tail, args) is True
        assert args.live_mode is False and args.auto_start is False
        assert args.auto_end is False and args.clear_logs is False
        assert args.parallel_run is False

    def test_placeholder_and_unknown_tokens_skipped(self) -> None:
        args = _holder()
        tail = ["0", "--duration", "120", "--scheme", "Italian", "--live"]
        assert apply_handshake_segment(tail, args) is True
        assert args.live_mode is True

    def test_returns_false_when_not_one_token_matched(self) -> None:
        args = _holder()
        assert apply_handshake_segment(["0", "--workers", "8"], args) is False

    def test_empty_tail_writes_nothing(self) -> None:
        args = _holder()
        assert apply_handshake_segment([], args) is False


class TestHandshakeGoldenTable:
    """argv -> fields captured from the pre-refactor ladders (post-B1).

    Vectors mirror the Master Driver's argv layouts (arg_builder) plus the
    scan-only shapes the per-tool ladders historically accepted. Recorded
    against the shared ``_GoldenArgs`` holder; per-tool parity is owned by
    each tool's own unedited ``tests/test_cli_args.py``.
    """

    GOLDEN: list[tuple[str, list[str], dict[str, bool]]] = [
        pytest.param(
            "driver_full_live",
            [
                "prog",
                "<DIR>",
                "0",
                "--live",
                "--start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ],
            {
                "live_mode": True,
                "auto_start": True,
                "auto_end": True,
                "clear_logs": True,
                "parallel_run": True,
            },
            id="driver_full_live scan-from-2 ladder",
        ),
        pytest.param(
            "driver_full_dry",
            [
                "prog",
                "<DIR>",
                "0",
                "--dry",
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ],
            {
                "live_mode": False,
                "auto_start": False,
                "auto_end": False,
                "clear_logs": False,
                "parallel_run": False,
            },
            id="driver_full_dry scan-from-2 ladder",
        ),
        pytest.param(
            "driver_min",
            ["prog", "<DIR>"],
            {
                "live_mode": False,
                "auto_start": False,
                "auto_end": False,
                "clear_logs": False,
                "parallel_run": False,
            },
            id="driver_min (no flags; defaults held)",
        ),
        pytest.param(
            "double_dry_live",
            ["prog", "<DIR>", "--dry", "--live"],
            {
                "live_mode": True,
                "auto_start": False,
                "auto_end": False,
                "clear_logs": False,
                "parallel_run": False,
            },
            id="double_dry_live last-occurrence-wins",
        ),
        pytest.param(
            "double_live_dry",
            ["prog", "<DIR>", "--live", "--dry"],
            {
                "live_mode": False,
                "auto_start": False,
                "auto_end": False,
                "clear_logs": False,
                "parallel_run": False,
            },
            id="double_live_dry last-occurrence-wins",
        ),
        pytest.param(
            "neg_at_2",
            ["prog", "<DIR>", "-16.0", "--live", "--start", "--end"],
            {
                "live_mode": True,
                "auto_start": True,
                "auto_end": True,
                "clear_logs": False,
                "parallel_run": False,
            },
            id="neg_at_2 (LUFS-like token not a handshake token)",
        ),
    ]

    @pytest.mark.parametrize("name,tail,expected", GOLDEN)
    def test_scan_ladder_golden(
        self, name: str, tail: list[str], expected: dict[str, bool]
    ) -> None:
        assert name  # label ping
        real_dir = mkdtemp()
        argv = [t.replace("<DIR>", real_dir) for t in tail]
        args = _GoldenArgs()
        result = apply_handshake_segment(argv[2:], args)
        assert result is (
            any(
                f in argv
                for f in (
                    "--live",
                    "--dry",
                    "--start",
                    "--no-start",
                    "--end",
                    "--no-end",
                    "--clear-logs",
                    "--no-clear-logs",
                    "--parallel-run",
                    "--no-parallel-run",
                )
            )
        )
        for field, value in expected.items():
            assert getattr(args, field) is value, f"{name}: {field}"


class TestPrintToolUsageError:
    """The single owner of the '<tool>: <error>' stderr writer."""

    def test_writes_prefixed_line_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_tool_usage_error("BPM Analyzer", "Coverage must be 0-100%, got: 150")
        out, err = capsys.readouterr()
        assert out == ""
        assert err == "BPM Analyzer: Coverage must be 0-100%, got: 150\n"

    def test_no_stdout_side_effects(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_tool_usage_error("Album Art Sync", "Embed size must be numeric, got: x")
        out, err = capsys.readouterr()
        assert out == ""
        assert err == "Album Art Sync: Embed size must be numeric, got: x\n"


class TestValidateCliArgs:
    """Tests for validate_cli_args function."""

    def test_valid_args_returns_empty_list(self) -> None:
        """Test valid arguments return no errors."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=True),
        ):
            args = argparse.Namespace(
                source="/valid/source",
                output="/valid/output",
                sensitivity=5.0,
                width=10.0,
                threshold=-40.0,
                fade_in=100,
                fade_out=100,
                target_lufs=-16.0,
                tolerance=1.0,
            )
            errors = validate_cli_args(args)
            assert errors == []

    def test_nonexistent_source_directory(self) -> None:
        """Test nonexistent source directory returns error."""
        args = argparse.Namespace(source="/nonexistent/path/12345")
        errors = validate_cli_args(args)
        assert any("does not exist" in e for e in errors)

    def test_source_not_a_directory(self) -> None:
        """Test source that is not a directory returns error."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=False),
        ):
            args = argparse.Namespace(source="/some/file.txt")
            errors = validate_cli_args(args)
            assert any("not a directory" in e for e in errors)

    def test_invalid_sensitivity_range(self) -> None:
        """Test sensitivity out of range returns error."""
        args = argparse.Namespace(sensitivity=15.0)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Sensitivity" in errors[0]

    def test_invalid_width_zero_returns_error(self) -> None:
        args = argparse.Namespace(width=0)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Width" in errors[0]

    def test_invalid_width_negative_returns_error(self) -> None:
        args = argparse.Namespace(width=-5)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Width" in errors[0]

    def test_invalid_threshold_positive_returns_error(self) -> None:
        args = argparse.Namespace(threshold=5.0)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Threshold" in errors[0]

    def test_valid_threshold_zero_passes(self) -> None:
        args = argparse.Namespace(threshold=0.0)
        errors = validate_cli_args(args)
        assert "Threshold" not in " ".join(errors)

    def test_invalid_fade_in_negative_returns_error(self) -> None:
        args = argparse.Namespace(fade_in=-1)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Fade-in" in errors[0]

    def test_valid_fade_in_zero_passes(self) -> None:
        args = argparse.Namespace(fade_in=0)
        errors = validate_cli_args(args)
        assert "Fade-in" not in " ".join(errors)

    def test_invalid_fade_out_negative_returns_error(self) -> None:
        args = argparse.Namespace(fade_out=-10)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Fade-out" in errors[0]

    def test_valid_fade_out_zero_passes(self) -> None:
        args = argparse.Namespace(fade_out=0)
        errors = validate_cli_args(args)
        assert "Fade-out" not in " ".join(errors)

    def test_invalid_target_lufs_positive_returns_error(self) -> None:
        args = argparse.Namespace(target_lufs=5.0)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "LUFS" in errors[0]

    def test_valid_target_lufs_negative_passes(self) -> None:
        args = argparse.Namespace(target_lufs=-14.0)
        errors = validate_cli_args(args)
        assert "LUFS" not in " ".join(errors)

    def test_invalid_tolerance_negative_returns_error(self) -> None:
        args = argparse.Namespace(tolerance=-0.5)
        errors = validate_cli_args(args)
        assert len(errors) == 1
        assert "Tolerance" in errors[0]

    def test_valid_tolerance_zero_passes(self) -> None:
        args = argparse.Namespace(tolerance=0)
        errors = validate_cli_args(args)
        assert "Tolerance" not in " ".join(errors)

    def test_returns_empty_list_for_valid_all_fields(self) -> None:
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=True),
        ):
            args = argparse.Namespace(
                source="/valid/src",
                output="/valid/out",
                sensitivity=5.0,
                width=10.0,
                threshold=-40.0,
                fade_in=100,
                fade_out=100,
                target_lufs=-14.0,
                tolerance=1.0,
            )
            errors = validate_cli_args(args)
            assert errors == []

    def test_output_path_validation(self) -> None:
        """Output path must be validated when present."""
        args = argparse.Namespace(output="/nonexistent/output_xyz_test")
        errors = validate_cli_args(args)
        assert any("Output directory does not exist" in e for e in errors)

    def test_output_not_a_directory(self) -> None:
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.is_dir", return_value=False),
        ):
            args = argparse.Namespace(output="/some/file.txt")
            errors = validate_cli_args(args)
            assert any("not a directory" in e for e in errors)


class TestUniversalCLIHandler:
    """Tests for UniversalCLIHandler class."""

    def test_initialization(self) -> None:
        """Test handler initializes with app instance."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)
        assert handler.app == mock_app

    def test_apply_cli_args_source_pattern(self) -> None:
        """Test detection and handling of source pattern."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            source="/source/dir", output="/output/dir", auto_end=True, auto_start=False
        )

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()

        with patch.object(handler, "_apply_source_pattern") as mock_apply:
            mock_apply.return_value = False
            handler.apply_cli_args(
                args, source_var=mock_source_var, output_var=mock_output_var
            )
            mock_apply.assert_called_once()

    def test_apply_cli_args_folder_pattern(self) -> None:
        """Test detection and handling of folder pattern."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(folder_path="/folder/path", auto_start=True)

        mock_folder_var = MagicMock()

        with patch.object(handler, "_apply_folder_pattern") as mock_apply:
            mock_apply.return_value = True
            result = handler.apply_cli_args(args, folder_var=mock_folder_var)
            mock_apply.assert_called_once()
            assert result is True

    def test_apply_cli_args_directory_pattern(self) -> None:
        """Test detection and handling of directory pattern."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(directory="/some/dir", mode="extract", auto_end=False)

        mock_directory_var = MagicMock()

        with patch.object(handler, "_apply_directory_pattern") as mock_apply:
            mock_apply.return_value = False
            handler.apply_cli_args(args, directory_var=mock_directory_var)
            mock_apply.assert_called_once()

    def test_apply_cli_args_no_args_pattern(self) -> None:
        """Test handling when no CLI arguments provided."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace()

        with patch.object(handler, "_apply_no_args_pattern") as mock_apply:
            mock_apply.return_value = False
            result = handler.apply_cli_args(args)
            mock_apply.assert_called_once()
            assert result is False

    def test_apply_source_pattern_sets_directory(self) -> None:
        """Test source pattern applies directory correctly."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            source="/source/dir", output="/output/dir", auto_end=True, auto_start=False
        )

        mock_source_var = MagicMock()
        mock_output_var = MagicMock()

        handler._apply_source_pattern(
            args, source_var=mock_source_var, output_var=mock_output_var
        )

        mock_source_var.set.assert_called_once_with("/source/dir")
        mock_output_var.set.assert_called_once_with("/output/dir")

    def test_apply_source_pattern_sets_auto_end(self) -> None:
        """The source pattern must mirror auto_end onto the app and trigger
        auto-start when both the flag and the callback are present."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            source="/source/dir", output="/output/dir", auto_end=True, auto_start=True
        )

        auto_start = MagicMock()
        result = handler._apply_source_pattern(
            args,
            source_var=MagicMock(),
            output_var=MagicMock(),
            auto_start_func=auto_start,
            auto_end_var=MagicMock(),
        )

        assert mock_app.auto_end is True
        assert result is True

    def test_apply_folder_pattern_sets_run_mode(self) -> None:
        """Folder pattern must mirror live_mode/dry-run onto run_mode and
        auto_end onto the app attribute."""
        mock_app = MagicMock()
        mock_app.run_mode = MagicMock()
        mock_app.auto_end = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            folder_path="/folder/path",
            live_mode=True,
            auto_end=True,
            auto_start=False,
        )

        handler._apply_folder_pattern(args, folder_var=MagicMock())

        mock_app.run_mode.set.assert_called_once_with("Live Update")

    def test_apply_directory_pattern_triggers_auto_start(self) -> None:
        """The directory pattern must trigger auto-start when both the flag
        and the callback are present."""
        mock_app = MagicMock()
        mock_app.auto_end = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            directory="/extract/dir",
            mode="extract",
            auto_end=True,
            auto_start=True,
        )

        auto_start = MagicMock()
        result = handler._apply_directory_pattern(
            args,
            directory_var=MagicMock(),
            auto_start_func=auto_start,
        )

        assert result is True

    def test_apply_app_specific_args_all_attributes(self) -> None:
        """Every supported app-specific argument must be applied when the
        app exposes the matching attribute."""
        mock_app = MagicMock()
        for attr in (
            "target_lufs",
            "tolerance",
            "scheme",
            "min_coverage",
            "embed_size",
            "purge",
            "preserve_lyrics",
            "preserve_album_artist",
            "preserve_embedded_art",
            "bpm_range_min",
            "bpm_range_max",
            "analysis_duration",
            "parallel_mode",
            "max_workers",
            "threshold",
            "fade_var",
            "fade_in_duration",
            "fade_out_duration",
        ):
            setattr(mock_app, attr, MagicMock())
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            target_lufs=-14.0,
            tolerance=2.0,
            scheme="Italian",
            min_coverage=60,
            embed_size=1000,
            purge=True,
            preserve_lyrics=True,
            preserve_album_artist=True,
            preserve_embedded_art=True,
            bpm_min=60,
            bpm_max=180,
            duration=30,
            parallel_mode=True,
            max_workers=4,
            threshold=-40.0,
            apply_fade=True,
            fade_in_ms=150,
            fade_out_ms=250,
        )
        handler._apply_app_specific_args(args)

        mock_app.scheme.set.assert_called_once_with("Italian")
        mock_app.min_coverage.set.assert_called_once_with(60)
        mock_app.embed_size.set.assert_called_once_with(1000)
        mock_app.purge.set.assert_called_once_with(True)
        mock_app.preserve_lyrics.set.assert_called_once_with(True)
        mock_app.preserve_album_artist.set.assert_called_once_with(True)
        mock_app.preserve_embedded_art.set.assert_called_once_with(True)
        mock_app.bpm_range_min.set.assert_called_once_with(60)
        mock_app.bpm_range_max.set.assert_called_once_with(180)
        mock_app.analysis_duration.set.assert_called_once_with(30)
        mock_app.parallel_mode.set.assert_called_once_with(True)
        mock_app.max_workers.set.assert_called_once_with(4)
        mock_app.threshold.set.assert_called_once_with(-40.0)
        mock_app.fade_var.set.assert_called_once_with(True)
        mock_app.fade_in_duration.set.assert_called_once_with(150)
        mock_app.fade_out_duration.set.assert_called_once_with(250)

    def test_apply_folder_pattern_sets_folder(self) -> None:
        """Test folder pattern applies folder path correctly."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(
            folder_path="/folder/path", auto_start=True, auto_end=False
        )

        mock_folder_var = MagicMock()

        handler._apply_folder_pattern(args, folder_var=mock_folder_var)

        mock_folder_var.set.assert_called_once_with("/folder/path")

    def test_apply_directory_pattern_sets_directory(self) -> None:
        """Test directory pattern (ASX Extractor) applies correctly."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)
        mock_app.asx_action_mode = MagicMock()

        args = argparse.Namespace(
            directory="/extract/dir", mode="test_mode", auto_end=False, auto_start=True
        )

        mock_directory_var = MagicMock()

        with patch.object(mock_app.asx_action_mode, "set") as mock_set:
            handler._apply_directory_pattern(args, directory_var=mock_directory_var)
            mock_directory_var.set.assert_called_once_with("/extract/dir")
            mock_set.assert_called_once_with("test_mode")

    def test_apply_no_args_pattern_returns_false(self) -> None:
        """Test no-args pattern returns False for auto-start."""
        mock_app = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        result = handler._apply_no_args_pattern()
        assert result is False

    def test_apply_app_specific_args_replaygain(self) -> None:
        """Test app-specific args for ReplayGain/Audio Normalizer."""
        mock_app = MagicMock()
        mock_app.target_lufs = MagicMock()
        mock_app.tolerance = MagicMock()
        handler = UniversalCLIHandler(mock_app)

        args = argparse.Namespace(target_lufs=-14.0, tolerance=2.0)
        handler._apply_app_specific_args(args)

        mock_app.target_lufs.set.assert_called_once_with(-14.0)
        mock_app.tolerance.set.assert_called_once_with(2.0)
