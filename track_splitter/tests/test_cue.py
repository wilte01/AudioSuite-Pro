"""Tests for the split's CUE sheet.

The sheet describes the source image at the offsets the split used, so the
strong lock is a round trip through the shared parser: the numbers a reader
gets back must be the numbers the tracks were cut at.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

from pathlib import Path

from audio_suite_shared.cue_parser import parse_cue_file
from track_splitter.core.cue import GENERATOR_REM, build_track_cue, write_track_cue
from track_splitter.core.models import Track

TRACKS = [
    Track(number=1, start_ms=0, end_ms=4500, title="Overture"),
    Track(number=2, start_ms=4500, end_ms=10_000, title="Finale"),
]


class TestBuildTrackCue:
    def test_the_sheet_describes_the_source_with_its_offsets(self) -> None:
        sheet = build_track_cue(source_name="gig.flac", tracks=TRACKS, title="Gig")
        assert 'FILE "gig.flac" FLAC' in sheet
        assert 'TITLE "Gig"' in sheet
        # 4500 ms is 337.5 CD frames, which the format quantises to 00:04:38.
        assert "INDEX 01 00:00:00" in sheet
        assert "INDEX 01 00:04:38" in sheet
        assert f"REM {GENERATOR_REM}" in sheet

    def test_it_ends_with_one_newline(self) -> None:
        sheet = build_track_cue(source_name="gig.wav", tracks=TRACKS)
        assert sheet.endswith("\n") and not sheet.endswith("\n\n")


class TestWriteTrackCue:
    def test_the_written_sheet_round_trips_through_the_parser(
        self, tmp_path: Path
    ) -> None:
        sheet = build_track_cue(
            source_name="gig.flac",
            tracks=TRACKS,
            title="Gig",
            performer="The Band",
        )
        path = write_track_cue(tmp_path / "gig.cue", sheet)

        parsed = parse_cue_file(path)
        assert parsed.title == "Gig"
        assert parsed.performer == "The Band"
        entry = parsed.files[0]
        assert entry.filename == "gig.flac"
        assert [track.number for track in entry.tracks] == [1, 2]
        # The format stores frames, so an offset can differ by up to one frame
        # (13.3 ms); anything larger means the sheet and the split disagree.
        for parsed_track, planned in zip(entry.tracks, TRACKS, strict=True):
            assert abs(parsed_track.index01.start_ms - planned.start_ms) <= 14
        assert [track.title for track in entry.tracks] == ["Overture", "Finale"]

    def test_a_sheet_without_a_final_newline_gains_one(self, tmp_path: Path) -> None:
        path = write_track_cue(tmp_path / "x.cue", 'TITLE "x"')
        assert path.read_text(encoding="utf-8") == 'TITLE "x"\n'
