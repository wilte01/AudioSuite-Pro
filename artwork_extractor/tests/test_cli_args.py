"""Tests for the Artwork Extractor's launcher arguments.

Changed in 2.6.0: new module — the Artwork Extractor's handshake.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from artwork_extractor.utils.cli_args import ArtworkArgs, parse


def test_a_bare_launch_parses_to_defaults() -> None:
    args = parse(["prog"])

    assert args.sidecar_name == "cover"
    assert args.force is False
    assert args.recursive is False


def test_the_driver_handshake_values_survive(tmp_path: Path) -> None:
    args = parse(
        [
            "prog",
            str(tmp_path),
            "--dry",
            "--start",
            "--name",
            "folder",
            "--force",
            "--recursive",
        ]
    )

    assert isinstance(args, ArtworkArgs)
    assert args.folder_path == str(tmp_path)
    assert args.live_mode is False
    assert args.auto_start is True
    assert args.sidecar_name == "folder"
    assert args.force is True
    assert args.recursive is True


def test_the_last_spelling_of_a_pair_wins(tmp_path: Path) -> None:
    """A builder that repeats a pair must read the way the argv is written."""
    args = parse(["prog", str(tmp_path), "--force", "--no-force", "--recursive"])

    assert args.force is False
    assert args.recursive is True


def test_a_name_carrying_a_path_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse(["prog", str(tmp_path), "--name", "../escape"])


def test_a_missing_folder_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse(["prog", str(tmp_path / "nope")])
