"""Tests for the Track Splitter's launcher argument parser.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from track_splitter.utils import cli_args


def _argv(folder: Path, *extra: str) -> list[str]:
    return ["Track_Splitter.pyw", str(folder), *extra]


class TestParse:
    def test_it_reads_every_option_and_the_handshake(self, tmp_path: Path) -> None:
        args = cli_args.parse(
            _argv(
                tmp_path,
                "--dry",
                "--no-start",
                "--no-end",
                "--output-dir",
                str(tmp_path / "out"),
                "--min-silence",
                "500",
                "--silence-db",
                "-40",
                "--min-track",
                "2000",
                "--boundary",
                "start",
                "--naming",
                "{track}",
                "--no-cue",
            )
        )

        assert args.folder_path == str(tmp_path)
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.output_dir == str(tmp_path / "out")
        assert args.min_silence == "500"
        assert args.silence_db == "-40"
        assert args.min_track == "2000"
        assert args.boundary == "start"
        assert args.naming == "{track}"
        assert args.cue is False

    def test_the_defaults_are_the_cli_defaults(self, tmp_path: Path) -> None:
        args = cli_args.parse(_argv(tmp_path))
        assert args.boundary == "midpoint"
        assert args.cue is True
        assert args.min_silence == ""

    def test_no_arguments_is_not_an_error(self) -> None:
        assert cli_args.parse(["Track_Splitter.pyw"]).folder_path == ""

    def test_an_unknown_boundary_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_args.parse(_argv(tmp_path, "--boundary", "middle"))
        assert excinfo.value.code == 1

    def test_a_missing_folder_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_args.parse(_argv(tmp_path / "does-not-exist"))
        assert excinfo.value.code == 1
