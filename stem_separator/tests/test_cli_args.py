"""Tests for the Stem Separator's GUI argument parser.

The parser is what the Master Driver and a launcher invoke, so its defaults
must match the tool's own (`htdemucs`, every stem, auto device) and an invalid
stem or model must fail at launch rather than in the middle of a run.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stem_separator.core.models import DEFAULT_MODEL, STEM_NAMES
from stem_separator.utils import cli_args


def _parse(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> object:
    monkeypatch.setattr(sys, "argv", ["Stem_Separator.pyw", *argv])
    return cli_args.parse()


class TestDefaults:
    """No arguments opens the GUI on its own defaults."""

    def test_no_arguments_is_a_blank_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _parse(monkeypatch, [])

        assert args.folder_path is None
        assert args.live_mode is False
        assert args.output_dir == ""
        assert args.model == DEFAULT_MODEL
        assert args.stems == STEM_NAMES
        assert args.mix is False
        assert args.device == "auto"
        assert args.auto_start is False
        assert args.auto_end is False


class TestToolOptions:
    """A driver launch maps every flag onto the parsed namespace."""

    def test_a_full_driver_launch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        args = _parse(
            monkeypatch,
            [
                str(tmp_path),
                "--live",
                "--start",
                "--end",
                "--output-dir",
                str(tmp_path / "stems"),
                "--model",
                "htdemucs_ft",
                "--stems",
                "vocals,bass",
                "--mix",
                "--device",
                "cpu",
            ],
        )

        assert args.folder_path == str(tmp_path)
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.output_dir == str(tmp_path / "stems")
        assert args.model == "htdemucs_ft"
        assert args.stems == ("vocals", "bass")
        assert args.mix is True
        assert args.device == "cpu"

    def test_dry_is_the_default_and_live_is_explicit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert _parse(monkeypatch, [str(tmp_path)]).live_mode is False
        assert _parse(monkeypatch, [str(tmp_path), "--dry"]).live_mode is False

    def test_driver_handshake_flags_are_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _parse(monkeypatch, ["--clear-logs", "--parallel-run"])

        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_unknown_arguments_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        args = _parse(monkeypatch, ["--something-new"])

        assert args.folder_path is None


class TestValidation:
    """A value the tool cannot honour fails at launch."""

    def test_unknown_stem_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _parse(monkeypatch, ["--stems", "piano"])

    def test_empty_stem_list_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _parse(monkeypatch, ["--stems", ","])

    def test_unknown_model_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _parse(monkeypatch, ["--model", "mdx_extra"])

    def test_missing_folder_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _parse(monkeypatch, ["/definitely/not/here"])
