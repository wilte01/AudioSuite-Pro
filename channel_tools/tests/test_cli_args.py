"""The launcher handshake parser.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_suite_shared import channel_ops
from channel_tools.utils import cli_args


class TestDefaults:
    def test_no_arguments_yields_the_defaults(self) -> None:
        args = cli_args.parse(["Channel_Tools.pyw"])
        assert args.folder_path == ""
        assert args.operation == channel_ops.DEFAULT_OPERATION
        assert args.live_mode is False


class TestParsing:
    def test_every_option_reaches_its_field(self, tmp_path: Path) -> None:
        args = cli_args.parse(
            [
                "Channel_Tools.pyw",
                str(tmp_path),
                "--operation",
                "width",
                "--width",
                "50",
                "--source-channel",
                "right",
                "--invert",
                "left",
                "--dry",
                "--start",
                "--no-end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.operation == "width"
        assert args.width == "50"
        assert args.source_channel == "right"
        assert args.invert_target == "left"
        assert args.live_mode is False
        assert args.auto_start is True
        assert args.auto_end is False
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_live_is_read_from_the_mode_slot(self, tmp_path: Path) -> None:
        args = cli_args.parse(["Channel_Tools.pyw", str(tmp_path), "--live"])
        assert args.live_mode is True


class TestRefusals:
    def test_an_unknown_operation_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli_args.parse(["Channel_Tools.pyw", str(tmp_path), "--operation", "bogus"])
        assert exit_info.value.code == 1
        assert "Unknown channel operation" in capsys.readouterr().err

    def test_a_non_numeric_width_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exit_info:
            cli_args.parse(["Channel_Tools.pyw", str(tmp_path), "--width", "wide"])
        assert exit_info.value.code == 1
        assert "--width must be a number" in capsys.readouterr().err

    def test_a_missing_folder_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "no-such-folder"
        with pytest.raises(SystemExit) as exit_info:
            cli_args.parse(["Channel_Tools.pyw", str(missing)])
        assert exit_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err
