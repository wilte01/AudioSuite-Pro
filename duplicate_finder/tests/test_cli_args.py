"""Tests for the Duplicate Finder's launcher argument parsing.

The Master Driver passes a fixed positional block and then this tool's options,
so the tests pin the slots *and* the option block: a shifted argv must fail like
its peers rather than be read as "no mode passed".

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from duplicate_finder.core.models import DEFAULT_THRESHOLD
from duplicate_finder.utils.cli_args import (
    DuplicateFinderArgs,
    looks_like_driver_argv,
    parse,
)


def _parse(*args: str) -> DuplicateFinderArgs:
    """Parse *args* as the argv tail.

    Args:
        *args: Tokens after the program name.

    Returns:
        The parsed arguments.
    """
    with patch.object(sys, "argv", ["Duplicate_Finder.pyw", *args]):
        return parse()


class TestDefaults:
    """No arguments, no validation, no surprises."""

    def test_no_arguments_give_the_defaults(self) -> None:
        args = parse([])

        assert args.folder_path == ""
        assert args.threshold == DEFAULT_THRESHOLD
        assert args.quarantine_dir == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_a_lone_folder_is_parsed(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path))

        assert args.folder_path == str(tmp_path)


class TestHandshakeSlots:
    """The positional block the driver emits."""

    def test_dry_and_start_slots_are_read(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path), "--dry", "--start", "--no-end")

        assert args.live_mode is False
        assert args.auto_start is True
        assert args.auto_end is False

    def test_live_and_end_slots_are_read(self, tmp_path: Path) -> None:
        args = _parse(str(tmp_path), "--live", "--no-start", "--end")

        assert args.live_mode is True
        assert args.auto_start is False
        assert args.auto_end is True


class TestToolOptions:
    """This tool's own options, after the positional block."""

    def test_threshold_is_parsed(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--threshold", "0.05"
        )

        assert args.threshold == pytest.approx(0.05)

    def test_quarantine_folder_is_parsed(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path),
            "--dry",
            "--no-start",
            "--no-end",
            "--quarantine-dir",
            "D:/quarantine",
        )

        assert args.quarantine_dir == "D:/quarantine"

    def test_both_options_are_parsed_in_either_order(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path),
            "--live",
            "--start",
            "--end",
            "--quarantine-dir",
            "D:/q",
            "--threshold",
            "0.2",
        )

        assert (args.quarantine_dir, args.threshold) == ("D:/q", pytest.approx(0.2))

    def test_a_non_numeric_threshold_keeps_the_default(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--threshold", "abc"
        )

        assert args.threshold == DEFAULT_THRESHOLD

    def test_the_display_only_flags_are_accepted(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path),
            "--dry",
            "--no-start",
            "--no-end",
            "--clear-logs",
            "--parallel-run",
        )

        assert args.clear_logs is True
        assert args.parallel_run is True


class TestValidation:
    """A run that cannot start exits 1 with a message."""

    def test_a_missing_folder_exits(self) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _parse("D:/definitely/not/here", "--dry", "--no-start", "--no-end")

        assert exit_info.value.code == 1

    @pytest.mark.parametrize("threshold", ["0", "1.5", "-0.1"])
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

    def test_a_full_threshold_is_allowed(self, tmp_path: Path) -> None:
        args = _parse(
            str(tmp_path), "--dry", "--no-start", "--no-end", "--threshold", "1"
        )

        assert args.threshold == 1.0


class TestLooksLikeDriverArgv:
    """The window's guard against treating pytest's argv as a handshake."""

    def test_a_driver_mode_slot_is_recognised(self) -> None:
        assert looks_like_driver_argv(["app.pyw", "D:/music", "--live", "--start"])
        assert looks_like_driver_argv(["app.pyw", "D:/music", "--dry"])

    def test_any_other_argv_is_not_a_handshake(self) -> None:
        assert not looks_like_driver_argv(["app.pyw"])
        assert not looks_like_driver_argv(["app.pyw", "D:/music"])
        assert not looks_like_driver_argv(["pytest", "-q", "--no-header"])
