"""Tests for the joiner's launcher handshake.

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_joiner.utils import cli_args


@pytest.fixture()
def folder(tmp_path: Path) -> Path:
    return tmp_path


def _argv(folder: Path, *extra: str) -> list[str]:
    return ["Audio_Joiner.pyw", str(folder), *extra]


def test_the_folder_is_positional(folder: Path) -> None:
    assert cli_args.parse(_argv(folder)).folder_path == str(folder)


def test_order_and_output_are_read(folder: Path) -> None:
    args = cli_args.parse(_argv(folder, "--order", "b.wav,a.wav", "--output", "x.wav"))

    assert args.order == "b.wav,a.wav"
    assert args.output == "x.wav"


def test_the_boundary_lengths_are_read(folder: Path) -> None:
    args = cli_args.parse(_argv(folder, "--gap-ms", "500"))

    assert args.gap_ms == "500"
    assert args.crossfade_ms == ""


def test_a_gap_and_a_crossfade_together_is_a_usage_error(folder: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_args.parse(_argv(folder, "--gap-ms", "500", "--crossfade-ms", "500"))

    assert excinfo.value.code == 1


@pytest.mark.parametrize("value", ["soon", "-5"])
def test_a_bad_length_is_a_usage_error(folder: Path, value: str) -> None:
    with pytest.raises(SystemExit):
        cli_args.parse(_argv(folder, "--gap-ms", value))


def test_no_copy_is_read(folder: Path) -> None:
    assert cli_args.parse(_argv(folder, "--no-copy")).copy is False
    assert cli_args.parse(_argv(folder)).copy is True


def test_a_missing_folder_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        cli_args.parse(["Audio_Joiner.pyw", "no-such-folder"])


def test_a_bare_launch_parses_to_defaults() -> None:
    args = cli_args.parse(["Audio_Joiner.pyw"])

    assert args.folder_path == ""
    assert args.order == ""


def test_two_zeroed_boundaries_are_both_unset(folder: Path) -> None:
    """The driver sends both options with 0, which is no boundary at all.

    Comparing the raw strings made ``--gap-ms 0 --crossfade-ms 0`` look like a
    gap *and* a crossfade, so every Master Driver launch exited 1.
    """
    args = cli_args.parse(_argv(folder, "--gap-ms", "0", "--crossfade-ms", "0"))

    assert args.gap_ms == "0"
    assert args.crossfade_ms == "0"


def test_a_gap_and_a_crossfade_together_are_refused(folder: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli_args.parse(_argv(folder, "--gap-ms", "250", "--crossfade-ms", "500"))

    assert exit_info.value.code == 1


def test_a_negative_boundary_is_refused(folder: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli_args.parse(_argv(folder, "--gap-ms", "-1"))

    assert exit_info.value.code == 1
