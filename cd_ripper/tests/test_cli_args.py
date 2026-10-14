"""Tests for cd_ripper.utils.cli_args.

Covers the G2.4 contract: ``CD_Ripper.pyw`` (via ``cd_ripper.app.main``)
must parse the Master Driver's argv and pre-fill the GUI widgets.

Changed in 1.0.1: adds parser tests for the driver handshake.
"""

from __future__ import annotations

import sys

from cd_ripper.utils.cli_args import (
    FORMAT_DISPLAY,
    CdRipperArgs,
    parse,
    parse_track_selection,
    was_launched_from_driver,
)


class TestCdRipperArgs:
    def test_default_values(self) -> None:
        args = CdRipperArgs()
        assert args.output_dir == ""
        assert args.format == ""
        assert args.tracks == ""
        assert args.cue is False
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestParseTrackSelection:
    def test_empty_string(self) -> None:
        assert parse_track_selection("") == set()

    def test_single_track(self) -> None:
        assert parse_track_selection("3") == {3}

    def test_multiple_tracks(self) -> None:
        assert parse_track_selection("1,3,5") == {1, 3, 5}

    def test_whitespace_handling(self) -> None:
        assert parse_track_selection(" 1 , 3 , 5 ") == {1, 3, 5}

    def test_invalid_tokens_skipped(self) -> None:
        assert parse_track_selection("1,abc,3") == {1, 3}

    def test_negative_numbers_skipped(self) -> None:
        assert parse_track_selection("-1,2") == {2}


class TestParse:
    def test_bare_launch_returns_defaults(self) -> None:
        assert parse(["cd_ripper"]) == CdRipperArgs()

    def test_driver_argv_is_fully_parsed(self) -> None:
        args = parse(
            [
                "cd_ripper",
                "--output-dir",
                "D:/Rips",
                "--format",
                "flac",
                "--tracks",
                "1,3,5",
                "--cue",
                "--dry",
                "--start",
                "--end",
            ]
        )
        assert args.output_dir == "D:/Rips"
        assert args.format == "flac"
        assert args.tracks == "1,3,5"
        assert args.cue is True
        assert args.live_mode is False
        assert args.auto_start is True
        assert args.auto_end is True

    def test_unknown_flags_are_ignored(self) -> None:
        args = parse(["cd_ripper", "--future-flag", "x"])
        assert args.output_dir == ""

    def test_format_display_map_covers_all_driver_formats(self) -> None:
        expected = {
            "wav": "WAV",
            "mp3": "MP3",
            "flac": "FLAC",
            "ogg": "OGG",
            "m4a": "M4A",
            "opus": "Opus",
        }
        for fmt, display in expected.items():
            assert fmt in FORMAT_DISPLAY, f"{fmt} missing from FORMAT_DISPLAY"
            assert FORMAT_DISPLAY[fmt] == display

    def test_reexports_driver_helper(self) -> None:
        assert callable(was_launched_from_driver)
        assert "cd_ripper.utils.cli_args" in sys.modules
