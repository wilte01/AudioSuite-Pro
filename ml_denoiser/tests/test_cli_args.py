"""Tests for ``ml_denoiser.utils.cli_args``.

The GUI parser is what the Master Driver launches with, so its `--amount` unit
(percent) is a contract: passing a fraction by mistake would be read as 1 %.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ml_denoiser.utils.cli_args import parse


def _parse(*args: str) -> object:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sys, "argv", ["app.py", *args])
        return parse()


def _folder(tmp_path: Path) -> str:
    return str(tmp_path)


class TestDefaults:
    """A bare launch opens on Dry Run at a full denoise."""

    def test_no_arguments_is_dry_and_full(self) -> None:
        args = _parse()

        assert args.folder_path is None
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.amount == 1.0
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestAmount:
    """``--amount`` is a percentage on both entry points."""

    def test_the_default_is_one_hundred_percent(self) -> None:
        assert _parse().amount == 1.0

    @pytest.mark.parametrize(
        ("given", "expected"), [("1", 0.01), ("40", 0.4), ("100", 1.0)]
    )
    def test_a_percentage_becomes_a_fraction(self, given: str, expected: float) -> None:
        assert _parse("--amount", given).amount == pytest.approx(expected)

    @pytest.mark.parametrize("bad", ["0", "-5", "101", "lots"])
    def test_out_of_range_and_non_numeric_values_are_refused(self, bad: str) -> None:
        with pytest.raises(SystemExit):
            _parse("--amount", bad)


class TestFlags:
    """The shared run-mode and handshake flags are mirrored, not guessed."""

    def test_live_selects_live_mode(self, tmp_path: Path) -> None:
        args = _parse(_folder(tmp_path), "--live")

        assert args.live_mode is True
        assert args.folder_path == _folder(tmp_path)

    def test_start_and_end_are_carried(self, tmp_path: Path) -> None:
        args = _parse(_folder(tmp_path), "--start", "--end")

        assert args.auto_start is True
        assert args.auto_end is True

    def test_driver_display_flags_are_accepted(self, tmp_path: Path) -> None:
        """The driver appends these; the parser must not choke on them."""
        args = _parse(_folder(tmp_path), "--no-clear-logs", "--no-parallel-run")

        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_unknown_arguments_are_ignored(self, tmp_path: Path) -> None:
        args = _parse(_folder(tmp_path), "--something-new")

        assert args.folder_path == _folder(tmp_path)

    def test_a_missing_folder_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            _parse(str(tmp_path / "does-not-exist"))
