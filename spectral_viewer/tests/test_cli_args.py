"""Tests for the Spectral Viewer's launcher argument parser.

The Master Driver hands the tool `[path, --dry|--live, --start|--no-start,
--end|--no-end, ...]`; a value it cannot parse must fail with a message the
launcher logs, not with a traceback (or, worse, a silently wrong FFT size).

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_suite_shared.cli_dataclasses import CLIValidationError
from spectral_viewer.tests.audio_fixtures import write_tone_wav
from spectral_viewer.utils.cli_args import (
    MAX_N_FFT,
    MIN_N_FFT,
    SpectralViewerArgs,
    parse,
    validate_args,
)


@pytest.fixture()
def audio_file(tmp_path: Path) -> Path:
    return write_tone_wav(tmp_path / "track.wav", seconds=0.3)


class TestDefaults:
    def test_no_arguments_yields_defaults(self) -> None:
        args = parse(["Spectral_Viewer.pyw"])

        assert args.folder_path == ""
        assert args.n_fft == 2048
        assert args.db_range == pytest.approx(80.0)
        assert args.cmap == "magma"
        assert args.output_dir == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_path_only(self, audio_file: Path) -> None:
        args = parse(["Spectral_Viewer.pyw", str(audio_file)])

        assert args.folder_path == str(audio_file)
        assert validate_args(args) == []


class TestValueOptions:
    def test_named_values_are_coerced(self, audio_file: Path) -> None:
        args = parse(
            [
                "Spectral_Viewer.pyw",
                str(audio_file),
                "--output-dir",
                "C:/out",
                "--n-fft",
                "4096",
                "--db-range",
                "60.5",
                "--cmap",
                "viridis",
            ]
        )

        assert args.output_dir == "C:/out"
        assert args.n_fft == 4096
        assert args.db_range == pytest.approx(60.5)
        assert args.cmap == "viridis"

    def test_handshake_flags_reach_the_dataclass(self, audio_file: Path) -> None:
        args = parse(
            [
                "Spectral_Viewer.pyw",
                str(audio_file),
                "--live",
                "--start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )

        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_handshake_flags(self, audio_file: Path) -> None:
        args = parse(
            [
                "Spectral_Viewer.pyw",
                str(audio_file),
                "--dry",
                "--no-start",
                "--no-end",
            ]
        )

        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_unknown_tokens_are_skipped(self, audio_file: Path) -> None:
        args = parse(["Spectral_Viewer.pyw", str(audio_file), "--mystery", "1"])

        assert args.n_fft == 2048
        assert args.folder_path == str(audio_file)


class TestValidation:
    def test_fft_below_the_floor_is_refused(self, audio_file: Path) -> None:
        args = SpectralViewerArgs(folder_path=str(audio_file), n_fft=MIN_N_FFT - 1)

        errors = validate_args(args)

        assert errors and "FFT size" in errors[0]

    def test_fft_above_the_ceiling_is_refused(self, audio_file: Path) -> None:
        args = SpectralViewerArgs(folder_path=str(audio_file), n_fft=MAX_N_FFT + 1)

        assert validate_args(args) != []

    def test_db_range_outside_the_band_is_refused(self, audio_file: Path) -> None:
        args = SpectralViewerArgs(folder_path=str(audio_file), db_range=5.0)

        errors = validate_args(args)

        assert errors and "Dynamic range" in errors[0]

    def test_non_numeric_fft_raises_validation_error(self, audio_file: Path) -> None:
        with pytest.raises(CLIValidationError, match="expects a int"):
            parse(["Spectral_Viewer.pyw", str(audio_file), "--n-fft", "wide"])

    def test_missing_option_value_raises(self, audio_file: Path) -> None:
        with pytest.raises(CLIValidationError, match="requires a value"):
            parse(["Spectral_Viewer.pyw", str(audio_file), "--output-dir"])

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CLIValidationError, match="does not exist"):
            parse(["Spectral_Viewer.pyw", str(tmp_path / "gone")])

    def test_a_file_path_is_accepted(self, audio_file: Path) -> None:
        args = parse(["Spectral_Viewer.pyw", str(audio_file)])

        assert Path(args.folder_path).is_file()
