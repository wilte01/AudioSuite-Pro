"""Tests for the FFmpeg ``silencedetect`` report parser.

The parser is the whole detector's risk surface: FFmpeg prints the events to
stderr as free text and leaves a trailing run without a ``silence_end``.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

from track_splitter.core.detector import parse_gaps

#: Recorded shape of a real ``silencedetect`` run over a 3 s file with two gaps.
REPORT = """\
[silencedetect @ 000001] silence_start: 0.500
[silencedetect @ 000001] silence_end: 1.300 | silence_duration: 0.800
[silencedetect @ 000001] silence_start: 1.800
[silencedetect @ 000001] silence_end: 2.600 | silence_duration: 0.800
Input #0, wav, from 'x.wav':
size=N/A time=00:00:03.10 bitrate=N/A speed= 194x
"""


class TestParseGaps:
    def test_pairs_every_run(self) -> None:
        gaps = parse_gaps(REPORT, 3100)
        assert [(g.start_ms, g.end_ms) for g in gaps] == [(500, 1300), (1800, 2600)]

    def test_a_trailing_run_is_closed_at_the_end(self) -> None:
        report = "[silencedetect @ 0] silence_start: 2.000\nsize=N/A time=00:00:03.00\n"
        gaps = parse_gaps(report, 3000)
        assert [(g.start_ms, g.end_ms) for g in gaps] == [(2000, 3000)]

    def test_an_unpaired_end_is_ignored(self) -> None:
        report = "[silencedetect @ 0] silence_end: 1.000 | silence_duration: 0.5\n"
        assert parse_gaps(report, 3000) == []

    def test_a_negative_start_is_clamped_to_zero(self) -> None:
        report = (
            "[silencedetect @ 0] silence_start: -0.001\n"
            "[silencedetect @ 0] silence_end: 0.500 | silence_duration: 0.5\n"
        )
        gaps = parse_gaps(report, 2000)
        assert (gaps[0].start_ms, gaps[0].end_ms) == (0, 500)

    def test_an_end_past_the_file_is_clamped(self) -> None:
        report = (
            "[silencedetect @ 0] silence_start: 1.500\n"
            "[silencedetect @ 0] silence_end: 9.000 | silence_duration: 7.5\n"
        )
        gaps = parse_gaps(report, 2000)
        assert gaps[0].end_ms == 2000

    def test_an_empty_report_has_no_gaps(self) -> None:
        assert parse_gaps("", 1000) == []
        assert parse_gaps("size=N/A time=00:00:01.00", 1000) == []

    def test_the_duration_property_is_the_run_length(self) -> None:
        gaps = parse_gaps(REPORT, 3100)
        assert [g.duration_ms for g in gaps] == [800, 800]
