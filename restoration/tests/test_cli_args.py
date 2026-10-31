"""Tests for the Restoration tool's launcher argument parsing.

Same fixed positional block as every folder tool, with this tool's two options
after it.  The spellings are the click command's own, so a user reading
``audiosuite declip --help`` sees what the driver emits.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from restoration.core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD
from restoration.utils.cli_args import RestorationArgs, looks_like_driver_argv, parse


def _parse(*args: str) -> RestorationArgs:
    """Parse *args* as the argv tail.

    Args:
        *args: Tokens after the program name.

    Returns:
        The parsed arguments.
    """
    with patch.object(sys, "argv", ["Restoration.pyw", *args]):
        return parse()


class TestDefaults:
    """No arguments, no validation."""

    def test_no_arguments_give_the_defaults(self) -> None:
        args = parse([])

        assert args.folder_path == ""
        assert args.threshold == DEFAULT_THRESHOLD
        assert args.run_ms == DEFAULT_MAX_RUN_MS
        assert args.live_mode is False

    def test_a_lone_folder_is_parsed(self, tmp_path: Path) -> None:
        assert _parse(str(tmp_path)).folder_path == str(tmp_path)


class TestHandshakeSlots:
    """The positional block the driver emits."""

    def test_dry_start_end_slots_are_read(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path), "--dry", "--start", "--end")

        assert (args.live_mode, args.auto_start, args.auto_end) == (False, True, True)

    def test_live_slot_is_read(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path), "--live", "--no-start", "--no-end")

        assert args.live_mode is True


class TestToolOptions:
    """This tool's own options, after the positional block."""

    def test_the_threshold_is_parsed(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--threshold", "0.75"
        )

        assert args.threshold == pytest.approx(0.75)

    def test_the_width_limit_is_parsed(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--max-run-ms", "12"
        )

        assert args.run_ms == 12

    def test_the_display_only_flags_are_accepted(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path), "--dry", "--no-start", "--no-end", "--clear-logs")

        assert args.clear_logs is True

    def test_a_non_numeric_width_keeps_the_default(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--max-run-ms", "wide"
        )

        assert args.run_ms == DEFAULT_MAX_RUN_MS


class TestValidation:
    """A run that cannot start exits 1 with a message."""

    def test_a_missing_folder_exits(self) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _parse("D:/definitely/not/here", "--dry", "--no-start", "--no-end")

        assert exit_info.value.code == 1

    @pytest.mark.parametrize("threshold", ["0", "1.5"])
    def test_an_out_of_range_threshold_exits(
        self, tmp_path: Path, threshold: str
    ) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _parse(
                str(tmp_path),
                "--dry",
                "--no-start",
                "--no-end",
                "--threshold",
                threshold,
            )

        assert exit_info.value.code == 1

    def test_a_zero_width_limit_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _parse(
                str(tmp_path), "--dry", "--no-start", "--no-end", "--max-run-ms", "0"
            )

        assert exit_info.value.code == 1


class TestLooksLikeDriverArgv:
    """The window's guard against treating any argv as a handshake."""

    def test_a_driver_mode_slot_is_recognised(self) -> None:
        assert looks_like_driver_argv(["app.pyw", "D:/music", "--dry"])
        assert looks_like_driver_argv(["app.pyw", "D:/music", "--live", "--start"])

    def test_any_other_argv_is_not_a_handshake(self) -> None:
        assert not looks_like_driver_argv(["app.pyw"])
        assert not looks_like_driver_argv(["pytest", "-q"])
