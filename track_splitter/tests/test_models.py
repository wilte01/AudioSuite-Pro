"""Tests for the split plan: settings validation and boundary arithmetic.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

import pytest

from audio_suite_shared.exceptions import AudioConfigValueError
from track_splitter.core.models import (
    BOUNDARY_RULES,
    Gap,
    SplitSettings,
    plan_tracks,
)


def _settings(**overrides: object) -> SplitSettings:
    values: dict[str, object] = {
        "min_silence_ms": 400,
        "silence_db": -45.0,
        "min_track_ms": 1000,
    }
    values.update(overrides)
    return SplitSettings(**values)  # type: ignore[arg-type]


class TestSplitSettings:
    def test_defaults_are_the_documented_ones(self) -> None:
        settings = SplitSettings()
        assert settings.min_silence_ms == 700
        assert settings.silence_db == -45.0
        assert settings.min_track_ms == 5000
        assert settings.boundary == "midpoint"
        assert settings.write_cue is False

    @pytest.mark.parametrize(
        "overrides",
        [
            {"min_silence_ms": 0},
            {"min_track_ms": 0},
            {"silence_db": 0.0},
            {"boundary": "middle"},
        ],
    )
    def test_an_unusable_setting_is_refused(self, overrides: dict[str, object]) -> None:
        with pytest.raises(AudioConfigValueError):
            _settings(**overrides)

    def test_every_boundary_rule_is_accepted(self) -> None:
        for rule in BOUNDARY_RULES:
            assert _settings(boundary=rule).boundary == rule


class TestPlanTracks:
    #: A 10 s file with one 1 s gap from 4 s to 5 s.
    GAPS = [Gap(start_ms=4000, end_ms=5000)]
    TOTAL = 10_000

    def test_midpoint_halves_the_gap_and_partitions_the_file(self) -> None:
        tracks = plan_tracks(self.GAPS, self.TOTAL, _settings())

        assert [(t.start_ms, t.end_ms) for t in tracks] == [
            (0, 4500),
            (4500, 10_000),
        ]
        assert [t.number for t in tracks] == [1, 2]

    def test_start_keeps_the_silence_with_the_following_track(self) -> None:
        tracks = plan_tracks(self.GAPS, self.TOTAL, _settings(boundary="start"))
        assert [(t.start_ms, t.end_ms) for t in tracks] == [(0, 4000), (4000, 10_000)]

    def test_end_keeps_the_silence_with_the_preceding_track(self) -> None:
        tracks = plan_tracks(self.GAPS, self.TOTAL, _settings(boundary="end"))
        assert [(t.start_ms, t.end_ms) for t in tracks] == [(0, 5000), (5000, 10_000)]

    @pytest.mark.parametrize("rule", BOUNDARY_RULES)
    def test_the_tracks_always_cover_the_whole_file(self, rule: str) -> None:
        tracks = plan_tracks(self.GAPS, self.TOTAL, _settings(boundary=rule))
        assert tracks[0].start_ms == 0
        assert tracks[-1].end_ms == self.TOTAL
        assert sum(t.duration_ms for t in tracks) == self.TOTAL

    def test_a_leading_gap_is_discarded_whatever_the_rule(self) -> None:
        gaps = [Gap(start_ms=0, end_ms=1000), Gap(start_ms=5000, end_ms=5500)]
        for rule in BOUNDARY_RULES:
            tracks = plan_tracks(gaps, self.TOTAL, _settings(boundary=rule))
            assert tracks[0].start_ms == 1000

    def test_a_trailing_gap_is_discarded_whatever_the_rule(self) -> None:
        gaps = [Gap(start_ms=3000, end_ms=4000), Gap(start_ms=9000, end_ms=self.TOTAL)]
        for rule in BOUNDARY_RULES:
            tracks = plan_tracks(gaps, self.TOTAL, _settings(boundary=rule))
            assert tracks[-1].end_ms == 9000

    def test_discarded_silence_is_outside_every_track(self) -> None:
        gaps = [Gap(start_ms=0, end_ms=1000), Gap(start_ms=9000, end_ms=self.TOTAL)]
        tracks = plan_tracks(gaps, self.TOTAL, _settings())
        assert sum(t.duration_ms for t in tracks) == 8000
        assert (tracks[0].start_ms, tracks[-1].end_ms) == (1000, 9000)

    def test_a_wholly_silent_source_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError):
            plan_tracks([Gap(start_ms=0, end_ms=self.TOTAL)], self.TOTAL, _settings())

    def test_no_gap_produces_one_track(self) -> None:
        tracks = plan_tracks([], self.TOTAL, _settings())
        assert len(tracks) == 1
        assert (tracks[0].start_ms, tracks[0].end_ms) == (0, self.TOTAL)

    def test_a_short_fragment_merges_instead_of_being_dropped(self) -> None:
        gaps = [Gap(start_ms=1000, end_ms=1500), Gap(start_ms=1700, end_ms=2200)]
        tracks = plan_tracks(gaps, self.TOTAL, _settings(min_track_ms=3000))

        assert sum(t.duration_ms for t in tracks) == self.TOTAL
        assert len(tracks) == 1, "the 200 ms fragment between the gaps is not a track"

    def test_a_short_first_fragment_merges_into_the_next_track(self) -> None:
        gaps = [Gap(start_ms=200, end_ms=800)]
        tracks = plan_tracks(gaps, self.TOTAL, _settings(min_track_ms=3000))

        assert len(tracks) == 1
        assert (tracks[0].start_ms, tracks[0].end_ms) == (0, self.TOTAL)

    def test_titles_are_numbered_from_the_tag_prefix(self) -> None:
        tracks = plan_tracks(
            self.GAPS, self.TOTAL, _settings(), title_prefix="Rehearsal"
        )
        assert [t.title for t in tracks] == ["Rehearsal 01", "Rehearsal 02"]

    def test_titles_fall_back_to_track_when_the_source_has_none(self) -> None:
        tracks = plan_tracks(self.GAPS, self.TOTAL, _settings())
        assert tracks[0].title == "Track 01"

    def test_a_source_with_no_length_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError):
            plan_tracks([], 0, _settings())
