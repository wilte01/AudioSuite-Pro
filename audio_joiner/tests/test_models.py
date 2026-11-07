"""Tests for the joiner's plan arithmetic.

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

import pytest

from audio_joiner.core.models import (
    JoinSettings,
    output_name,
    plan_duration_ms,
    validate_output_name,
    validate_overlap,
)
from audio_suite_shared.exceptions import AudioConfigValueError


class TestOutputNameValidation:
    """The output name is checked against the filesystem, not ASCII."""

    def test_a_legal_name_passes_unchanged(self) -> None:
        name = "1-03 Johnny, Don't Do It_joined.mp3"

        assert validate_output_name(f"D:/Music/{name}") == name

    def test_an_illegal_character_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="not a usable file name"):
            validate_output_name("D:/Music/bad|name.mp3")

    def test_a_reserved_device_name_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="not a usable file name"):
            validate_output_name("D:/Music/CON.mp3")


class TestSettings:
    def test_defaults_do_not_change_a_boundary(self) -> None:
        settings = JoinSettings()

        assert settings.gap_ms == 0
        assert settings.crossfade_ms == 0
        assert settings.processes_boundaries is False

    def test_a_gap_and_a_crossfade_are_refused_together(self) -> None:
        with pytest.raises(AudioConfigValueError, match="not both"):
            JoinSettings(gap_ms=500, crossfade_ms=500)

    def test_a_negative_length_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError):
            JoinSettings(gap_ms=-1)
        with pytest.raises(AudioConfigValueError):
            JoinSettings(crossfade_ms=-1)

    def test_either_boundary_setting_counts_as_processing(self) -> None:
        assert JoinSettings(gap_ms=100).processes_boundaries is True
        assert JoinSettings(crossfade_ms=100).processes_boundaries is True


class TestPlanDuration:
    def test_a_hard_join_is_the_sum(self) -> None:
        assert plan_duration_ms([1000, 2000, 500], JoinSettings()) == 3500

    def test_a_gap_adds_one_per_boundary(self) -> None:
        assert plan_duration_ms([1000, 2000, 500], JoinSettings(gap_ms=250)) == 4000

    def test_a_crossfade_removes_one_per_boundary(self) -> None:
        plan = plan_duration_ms([1000, 2000, 500], JoinSettings(crossfade_ms=100))

        assert plan == 3300

    def test_one_segment_has_no_boundary(self) -> None:
        assert plan_duration_ms([1200], JoinSettings(crossfade_ms=0)) == 1200

    def test_no_segments_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="at least one segment"):
            plan_duration_ms([], JoinSettings())

    def test_a_crossfade_longer_than_the_shortest_segment_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="not shorter"):
            plan_duration_ms([4000, 300], JoinSettings(crossfade_ms=300))

    def test_validate_overlap_allows_a_shorter_fade(self) -> None:
        validate_overlap([4000, 300], 299)


class TestOutputName:
    def test_the_marker_goes_between_the_stem_and_the_extension(self) -> None:
        assert output_name("01 intro.flac", ".flac") == "01 intro_joined.flac"

    def test_an_extension_without_its_dot_is_accepted(self) -> None:
        assert output_name("a.wav", "wav") == "a_joined.wav"

    def test_a_comma_in_the_first_name_is_kept(self) -> None:
        assert output_name("1-03 Johnny, Don't Do It.mp3", ".mp3") == (
            "1-03 Johnny, Don't Do It_joined.mp3"
        )

    def test_a_path_takes_only_its_file_name(self) -> None:
        assert output_name("D:/Music/a.mp3", ".mp3") == "a_joined.mp3"
