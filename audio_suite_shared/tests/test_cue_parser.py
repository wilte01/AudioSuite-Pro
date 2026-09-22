"""
tests/test_cue_parser.py — tests for audio_suite_shared/cue_parser.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_suite_shared.cue_parser import (
    CueIndex,
    CueParseError,
    CueSheet,
    parse_cue,
    parse_cue_file,
)

FULL_SHEET = """\
REM GENRE Rock
REM DATE 2024
CATALOG 00602458123456
PERFORMER "Various Artists"
TITLE "Compilation Album"
FILE "Compilation.flac" WAVE
  TRACK 01 AUDIO
    TITLE "First Song"
    PERFORMER "Band One"
    SONGWRITER "Writer One"
    ISRC USABC2400001
    FLAGS DCP
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Song"
    PERFORMER "Band Two"
    PREGAP 00:02:00
    INDEX 00 00:02:00
    INDEX 01 00:02:40
    POSTGAP 00:01:00
FILE "Bonus.mp3" MP3
  TRACK 03 AUDIO
    TITLE "Bonus Track"
"""


def _parse_full() -> CueSheet:
    return parse_cue(FULL_SHEET)


class TestFullSheetStructure:
    def test_sheet_level_fields(self):
        sheet = _parse_full()
        assert sheet.catalog == "00602458123456"
        assert sheet.performer == "Various Artists"
        assert sheet.title == "Compilation Album"
        assert sheet.rem == ("GENRE", "Rock", "DATE", "2024")

    def test_two_file_entries(self):
        sheet = _parse_full()
        assert len(sheet.files) == 2
        first, second = sheet.files
        assert first.filename == "Compilation.flac"
        assert first.file_type == "WAVE"
        assert second.filename == "Bonus.mp3"
        assert second.file_type == "MP3"

    def test_track_counts_per_file(self):
        sheet = _parse_full()
        assert len(sheet.files[0].tracks) == 2
        assert len(sheet.files[1].tracks) == 1

    def test_track_metadata_is_populated(self):
        sheet = _parse_full()
        track = sheet.files[0].tracks[0]
        assert track.number == 1
        assert track.mode == "AUDIO"
        assert track.title == "First Song"
        assert track.performer == "Band One"
        assert track.songwriter == "Writer One"
        assert track.isrc == "USABC2400001"
        assert track.flags == ("DCP",)
        assert track.rem == ()

    def test_pregap_postgap_stored(self):
        sheet = _parse_full()
        track = sheet.files[0].tracks[1]
        assert track.pregap == "00:02:00"
        assert track.postgap == "00:01:00"

    def test_index00_and_index01_kept_in_order(self):
        sheet = _parse_full()
        track = sheet.files[0].tracks[1]
        assert [i.number for i in track.indexes] == [0, 1]
        assert track.indexes[0].start_ms == 2000
        assert track.indexes[1].start_ms == 2533

    def test_index01_property_picks_index_number_one(self):
        sheet = _parse_full()
        track = sheet.files[0].tracks[1]
        assert track.index01 is not None
        assert track.index01.mm == 0
        assert track.index01.ss == 2
        assert track.index01.ff == 40


class TestIndexTiming:
    def test_frames_from_msf(self):
        assert CueIndex(1, 0, 2, 40).frames == 190

    def test_start_ms_rounds_to_frame(self):
        # 190 frames * 1000 / 75 = 2533.333 ms → round → 2533
        assert CueIndex(1, 0, 2, 40).start_ms == 2533

    def test_hour_and_minute_conversion(self):
        # 5 minutes exactly = 22500 frames → 300000 ms
        assert CueIndex(1, 5, 0, 0).start_ms == 300000

    def test_frozen(self):
        index = CueIndex(1, 0, 0, 0)
        with pytest.raises(Exception):
            index.mm = 1


class TestCompoundExpressions:
    def test_sheet_can_be_empty(self):
        sheet = parse_cue("")
        assert sheet.files == ()
        assert sheet.title is None

    def test_commands_are_case_insensitive(self):
        sheet = parse_cue(
            'PERFORMER "Artist"\nTITLE "Album"\nfile "x.wav" wave\n'
            '  track 01 data\n    title "Song"\n    index 01 00:00:00\n'
        )
        assert sheet.performer == "Artist"
        assert sheet.title == "Album"
        assert sheet.files[0].file_type == "WAVE"
        assert sheet.files[0].tracks[0].mode == "DATA"

    def test_quoted_values_with_spaces_kept_intact(self):
        sheet = parse_cue('PERFORMER "The Beatles"\nTITLE "Abbey Road"\n')
        assert sheet.performer == "The Beatles"
        assert sheet.title == "Abbey Road"

    def test_escaped_quote_inside_quoted_value(self):
        sheet = parse_cue('TITLE "A ""Quoted"" Title"\n')
        assert sheet.title == 'A "Quoted" Title'

    def test_unquoted_arguments_concatenated(self):
        sheet = parse_cue("REM GENRE Classic Rock Style\n")
        assert sheet.rem == ("GENRE", "Classic", "Rock", "Style")

    def test_blank_lines_ignored(self):
        sheet = parse_cue('\n\n  \nTITLE "Album"\n\n')
        assert sheet.title == "Album"

    def test_file_level_performer_title_scoped_to_file(self):
        sheet = parse_cue(
            'TITLE "Album"\nFILE "a.wav" WAVE\n  TITLE "File Title"\n'
            "  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n"
        )
        assert sheet.title == "Album"
        assert sheet.files[0].title == "File Title"
        assert sheet.files[0].tracks[0].title is None

    def test_track_level_performer_overrides_file(self):
        sheet = parse_cue(
            'PERFORMER "File Artist"\nFILE "a.wav" WAVE\n'
            '  TRACK 01 AUDIO\n    PERFORMER "Track Artist"\n    INDEX 01 00:00:00\n'
        )
        assert sheet.performer == "File Artist"
        assert sheet.files[0].tracks[0].performer == "Track Artist"


class TestErrorHandling:
    @pytest.mark.parametrize(
        "text",
        [
            "BOGUS 1 2\n",
            "INDEX 01 00:00:00\n",  # INDEX outside TRACK
            "TRACK 01 AUDIO\n",  # TRACK outside FILE
            "  TRACK 01 AUDIO\n    TRACK 02 AUDIO\n",  # TRACK outside FILE
            'FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n  INDEX 01 99:99:99\n',
            "PREGAP 00:02:00\n",  # PREGAP outside TRACK
            "POSTGAP 00:02:00\n",  # POSTGAP outside TRACK
            "ISRC USABC\n",  # ISRC outside TRACK
            'SONGWRITER "Nobody"\n',  # SONGWRITER outside TRACK
            "FLAGS DCP\n",  # FLAGS outside TRACK
            'FILE "a.wav" WAVE\nCATALOG 123\n',  # CATALOG after FILE
            "CATALOG 123 456\n",  # CATALOG with too many arguments
        ],
    )
    def test_invalid_sheets_raise(self, text):
        with pytest.raises(CueParseError):
            parse_cue(text)

    def test_unknown_command_reported_with_line_number(self):
        with pytest.raises(CueParseError, match="Line 3"):
            parse_cue('TITLE "A"\nPERFORMER "B"\nWHATEVER 1\n')

    def test_bad_msf_format(self):
        with pytest.raises(CueParseError):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00\n')

    def test_frames_out_of_range(self):
        with pytest.raises(CueParseError, match="frames"):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:75\n')

    def test_seconds_out_of_range(self):
        with pytest.raises(CueParseError, match="seconds"):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:60:00\n')

    def test_minutes_out_of_range(self):
        with pytest.raises(CueParseError, match="minutes"):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 600:00:00\n')

    def test_unterminated_quote(self):
        with pytest.raises(CueParseError, match="Unterminated"):
            parse_cue('TITLE "Never closed\n')

    def test_track_number_out_of_range(self):
        with pytest.raises(CueParseError):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 100 AUDIO\n')

    def test_track_number_non_numeric(self):
        with pytest.raises(CueParseError):
            parse_cue('FILE "a.wav" WAVE\n  TRACK AB AUDIO\n')

    def test_index_number_out_of_range(self):
        with pytest.raises(CueParseError):
            parse_cue('FILE "a.wav" WAVE\n  TRACK 01 AUDIO\n    INDEX 100 00:00:00\n')


class TestFileReading:
    def test_parse_cue_file_reads_utf8(self, tmp_path: Path):
        cue_file = tmp_path / "album.cue"
        cue_file.write_text(
            'PERFORMER "Artist"\nTITLE "Album"\n'
            'FILE "Album.flac" FLAC\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        sheet = parse_cue_file(cue_file)
        assert sheet.performer == "Artist"
        assert len(sheet.files[0].tracks) == 1

    def test_parse_cue_file_tolerates_bom(self, tmp_path: Path):
        cue_file = tmp_path / "bom.cue"
        cue_file.write_bytes(b'\xef\xbb\xbfTITLE "Album"\n')
        sheet = parse_cue_file(cue_file)
        assert sheet.title == "Album"

    def test_parse_cue_file_missing_raises(self, tmp_path: Path):
        with pytest.raises(OSError):
            parse_cue_file(tmp_path / "nope.cue")


class TestRoundTripWithGenerator:
    def test_generated_sheet_parses_identically(self):
        from audio_suite_shared.cue_generator import (
            CueFileSpec,
            TrackSpec,
            build_cue,
        )

        text = build_cue(
            title="Album",
            performer="Artist",
            files=(
                CueFileSpec(
                    filename="Album.flac",
                    tracks=(
                        TrackSpec(number=1, title="One", start_ms=0),
                        TrackSpec(number=2, title='Two "X"', start_ms=225000),
                    ),
                ),
            ),
        )
        sheet = parse_cue(text)
        assert sheet.title == "Album"
        assert sheet.performer == "Artist"
        track1, track2 = sheet.files[0].tracks
        assert track1.index01 is not None
        assert track1.index01.start_ms == 0
        assert track2.index01 is not None
        assert track2.index01.start_ms == 225000
        assert track2.title == 'Two "X"'
        assert track2.mode == "AUDIO"
