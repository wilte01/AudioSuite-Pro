"""Tests for the CUE Sheet Generator's launcher arguments.

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cue_sheet.utils.cli_args import CueSheetArgs, parse


def test_a_bare_launch_parses_to_defaults() -> None:
    assert parse(["prog"]).output == ""


def test_the_driver_handshake_values_survive(tmp_path: Path) -> None:
    args = parse(
        [
            "prog",
            str(tmp_path),
            "--dry",
            "--start",
            "--output",
            str(tmp_path / "x.cue"),
            "--album-title",
            "Gig",
            "--album-artist",
            "The Band",
        ]
    )

    assert isinstance(args, CueSheetArgs)
    assert args.folder_path == str(tmp_path)
    assert args.live_mode is False
    assert args.output == str(tmp_path / "x.cue")
    assert args.album_title == "Gig"
    assert args.album_artist == "The Band"


def test_a_missing_folder_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse(["prog", str(tmp_path / "nope")])
