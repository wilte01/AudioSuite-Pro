"""Tests for the launcher's argument parser.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pitch_time.utils.cli_args import parse


class TestParse:
    def test_the_folder_and_rate_are_read(self, tmp_path: Path) -> None:
        args = parse(["Pitch_Time.pyw", str(tmp_path), "--rate", "1.25"])

        assert args.folder_path == str(tmp_path)
        assert args.rate == "1.25"
        assert args.semitones == ""

    def test_the_driver_flags_reach_the_dataclass(self, tmp_path: Path) -> None:
        args = parse(
            [
                "Pitch_Time.pyw",
                str(tmp_path),
                "--semitones",
                "-2",
                "--dry",
                "--parallel-run",
            ]
        )

        assert args.semitones == "-2"
        assert args.live_mode is False
        assert args.parallel_run is True

    def test_no_arguments_is_a_blank_window(self) -> None:
        args = parse(["Pitch_Time.pyw"])

        assert args.folder_path == ""
        assert args.rate == ""

    def test_a_missing_folder_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exit_info:
            parse(["Pitch_Time.pyw", str(tmp_path / "absent")])

        assert exit_info.value.code == 1

    def test_a_non_numeric_rate_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exit_info:
            parse(["Pitch_Time.pyw", str(tmp_path), "--rate", "soon"])

        assert exit_info.value.code == 1
