"""
tests/test_cue_generator.py — tests for audio_suite_shared/cue_generator.py.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from audio_suite_shared.cue_generator import (
    CueFileSpec,
    TrackSpec,
    build_cue,
    format_msf,
    ms_to_frames,
    write_cue,
)


class TestMsf:
    @pytest.mark.parametrize(
        "frames,expected",
        [
            (0, "00:00:00"),
            (75, "00:01:00"),
            (4500, "01:00:00"),
            (187, "00:02:37"),
            (449999, "99:59:74"),
        ],
    )
    def test_format_msf_known_values(self, frames, expected):
        assert format_msf(frames) == expected

    def test_negative_clamped_to_zero(self):
        assert format_msf(-5) == "00:00:00"

    def test_overflow_clamped(self):
        assert format_msf(600 * 4500) == "599:59:74"

    def test_ms_to_frames_rounds(self):
        assert ms_to_frames(0) == 0
        assert ms_to_frames(1000) == 75
        assert ms_to_frames(2533) == 190


class TestBuildCue:
    def test_single_track_sheet(self):
        text = build_cue(
            files=(CueFileSpec(filename="Album.flac", tracks=(TrackSpec(1, "Song"),)),)
        )
        assert text == (
            'FILE "Album.flac" FLAC\n'
            "  TRACK 01 AUDIO\n"
            '    TITLE "Song"\n'
            "    INDEX 01 00:00:00\n"
        )

    def test_full_album_header(self):
        text = build_cue(
            title="Album",
            performer="Artist",
            rem=("GENRE Rock",),
            catalog="1234",
            files=(CueFileSpec(filename="Album.flac", tracks=(TrackSpec(1, "One"),)),),
        )
        lines = text.splitlines()
        assert lines[0] == "REM GENRE Rock"
        assert lines[1] == "CATALOG 1234"
        assert lines[2] == 'PERFORMER "Artist"'
        assert lines[3] == 'TITLE "Album"'
        assert lines[4] == 'FILE "Album.flac" FLAC'

    def test_multi_track_index_timestamps(self):
        text = build_cue(
            files=(
                CueFileSpec(
                    filename="Album.flac",
                    tracks=(
                        TrackSpec(1, "One", start_ms=0),
                        TrackSpec(2, "Two", start_ms=300000),
                        TrackSpec(3, "Three", start_ms=600000),
                    ),
                ),
            )
        )
        assert "    INDEX 01 00:00:00" in text
        assert "    INDEX 01 05:00:00" in text
        assert "    INDEX 01 10:00:00" in text

    def test_performer_and_isrc_emitted(self):
        text = build_cue(
            files=(
                CueFileSpec(
                    filename="x.wav",
                    tracks=(TrackSpec(1, "One", performer="Solo", isrc="USABC1"),),
                ),
            )
        )
        assert '    PERFORMER "Solo"' in text
        assert "    ISRC USABC1" in text

    def test_leading_number_zero_padded(self):
        text = build_cue(
            files=(CueFileSpec(filename="x.mp3", tracks=(TrackSpec(9, "Nine"),)),)
        )
        assert "  TRACK 09 AUDIO" in text

    def test_quotes_in_title_escaped(self):
        text = build_cue(
            files=(
                CueFileSpec(filename="x.wav", tracks=(TrackSpec(1, 'He said "Hi"'),)),
            )
        )
        assert '    TITLE "He said ""Hi"""' in text

    def test_no_trailing_blank_lines(self):
        text = build_cue(
            files=(CueFileSpec(filename="x.wav", tracks=(TrackSpec(1, "One"),)),)
        )
        assert text.endswith("\n")
        assert not text.endswith("\n\n")

    def test_empty_files_list_still_terminated(self):
        text = build_cue(files=())
        assert text == "\n"

    def test_file_type_passthrough(self):
        spec = CueFileSpec(filename="x.flac", file_type="FLAC")
        text = build_cue(files=(spec,))
        assert 'FILE "x.flac" FLAC' in text

    def test_each_file_spec_emits_its_own_block(self):
        """``files`` is a sequence: one FILE block per spec, in order.

        The ripper relies on this for track-per-file rips -- a sheet holding
        every track inside one FILE describes a single continuous image.
        """
        text = build_cue(
            files=(
                CueFileSpec(filename="01 - One.flac", tracks=(TrackSpec(1, "One"),)),
                CueFileSpec(filename="02 - Two.flac", tracks=(TrackSpec(2, "Two"),)),
            )
        )
        assert [line for line in text.splitlines() if line.startswith("FILE ")] == [
            'FILE "01 - One.flac" FLAC',
            'FILE "02 - Two.flac" FLAC',
        ]

    def test_multi_file_sheet_round_trips_to_distinct_images(self):
        """Parse back: two FILE entries, each naming its own image."""
        from audio_suite_shared.cue_parser import parse_cue

        text = build_cue(
            files=(
                CueFileSpec(filename="01 - One.flac", tracks=(TrackSpec(1, "One"),)),
                CueFileSpec(filename="02 - Two.flac", tracks=(TrackSpec(2, "Two"),)),
            )
        )
        sheet = parse_cue(text)
        assert [entry.filename for entry in sheet.files] == [
            "01 - One.flac",
            "02 - Two.flac",
        ]
        assert [[track.title for track in entry.tracks] for entry in sheet.files] == [
            ["One"],
            ["Two"],
        ]


class TestValidation:
    def test_track_number_zero_rejected(self):
        with pytest.raises(ValueError):
            TrackSpec(0, "Zero")

    def test_track_number_over_ninety_nine_rejected(self):
        with pytest.raises(ValueError):
            TrackSpec(100, "Too Many")

    def test_negative_start_ms_rejected(self):
        with pytest.raises(ValueError):
            TrackSpec(1, "Neg", start_ms=-1)

    def test_empty_filename_rejected(self):
        with pytest.raises(ValueError):
            CueFileSpec("")

    def test_empty_file_type_rejected(self):
        with pytest.raises(ValueError):
            CueFileSpec("x.wav", file_type="")

    def test_specs_are_frozen(self):
        spec = TrackSpec(1, "One")
        with pytest.raises(FrozenInstanceError):
            spec.title = "Changed"


class TestWriteCue:
    def test_write_cue_round_trips(self, tmp_path: Path):
        from audio_suite_shared.cue_parser import parse_cue

        cue_file = tmp_path / "album.cue"
        text = build_cue(
            files=(CueFileSpec(filename="Album.flac", tracks=(TrackSpec(1, "One"),)),)
        )
        write_cue(cue_file, text)
        assert cue_file.exists()
        sheet = parse_cue(cue_file.read_text(encoding="utf-8"))
        assert sheet.files[0].tracks[0].title == "One"

    def test_write_cue_adds_trailing_newline(self, tmp_path: Path):
        cue_file = tmp_path / "x.cue"
        write_cue(cue_file, 'TITLE "Album"')
        data = cue_file.read_bytes()
        assert data.endswith(b"\n")
        assert data.count(b"\n") == 1
