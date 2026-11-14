"""Tests for the pitch/time settings and their refusals.

The settings are the contract the window, the CLI and the Master Driver all
build, so a setting the engine cannot honour is refused here rather than
discovered once the audio work has happened.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import pytest

from audio_suite_shared.exceptions import AudioConfigValueError
from pitch_time.core.models import (
    MAX_RATE,
    MAX_SEMITONES,
    MIN_RATE,
    MIN_SEMITONES,
    MODE_PITCH,
    MODE_TEMPO,
    PitchTimeSettings,
    output_name,
)


class TestSettings:
    """A setting either describes a change or is refused with its reason."""

    def test_tempo_is_the_default_mode(self) -> None:
        settings = PitchTimeSettings(rate=1.25)

        assert settings.mode == MODE_TEMPO
        assert settings.factor == pytest.approx(1.25)

    def test_a_tempo_rate_of_one_is_neutral_not_refused(self) -> None:
        """A driver batch with defaults must report nothing to do, not fail."""
        settings = PitchTimeSettings(mode=MODE_TEMPO, rate=1.0)

        assert settings.is_neutral is True
        assert settings.factor == pytest.approx(1.0)

    def test_a_pitch_shift_of_zero_is_neutral_not_refused(self) -> None:
        settings = PitchTimeSettings(mode=MODE_PITCH, semitones=0.0)

        assert settings.is_neutral is True

    def test_a_changing_setting_is_not_neutral(self) -> None:
        assert PitchTimeSettings(rate=1.25).is_neutral is False
        assert PitchTimeSettings(mode=MODE_PITCH, semitones=-2.0).is_neutral is False

    def test_an_unknown_mode_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="mode"):
            PitchTimeSettings(mode="karaoke", rate=1.1)

    @pytest.mark.parametrize("rate", [MIN_RATE / 2, MAX_RATE * 2])
    def test_a_rate_outside_the_engine_range_is_refused(self, rate: float) -> None:
        with pytest.raises(AudioConfigValueError, match="rate"):
            PitchTimeSettings(mode=MODE_TEMPO, rate=rate)

    @pytest.mark.parametrize("semitones", [MIN_SEMITONES - 1, MAX_SEMITONES + 1])
    def test_a_shift_outside_the_engine_range_is_refused(
        self, semitones: float
    ) -> None:
        with pytest.raises(AudioConfigValueError, match="semitones"):
            PitchTimeSettings(mode=MODE_PITCH, semitones=semitones)

    def test_the_range_edges_are_accepted(self) -> None:
        assert PitchTimeSettings(mode=MODE_TEMPO, rate=MIN_RATE).rate == MIN_RATE
        assert PitchTimeSettings(mode=MODE_TEMPO, rate=MAX_RATE).rate == MAX_RATE
        assert (
            PitchTimeSettings(mode=MODE_PITCH, semitones=MIN_SEMITONES).semitones
            == MIN_SEMITONES
        )

    def test_an_octave_is_a_factor_of_two(self) -> None:
        assert PitchTimeSettings(
            mode=MODE_PITCH, semitones=12.0
        ).factor == pytest.approx(2.0)
        assert PitchTimeSettings(
            mode=MODE_PITCH, semitones=-12.0
        ).factor == pytest.approx(0.5)

    def test_the_description_names_the_change(self) -> None:
        assert "1.25" in PitchTimeSettings(rate=1.25).description
        assert "+2" in PitchTimeSettings(mode=MODE_PITCH, semitones=2.0).description


class TestOutputName:
    """The written file never replaces its source and says what it is."""

    def test_a_tempo_name_carries_the_rate(self) -> None:
        name = output_name("song.wav", PitchTimeSettings(rate=1.25))

        assert name == "song_tempo_1.25.wav"

    def test_a_pitch_name_carries_the_semitones(self) -> None:
        name = output_name(
            "song.flac", PitchTimeSettings(mode=MODE_PITCH, semitones=-2)
        )

        assert name == "song_pitch_-2st.flac"

    def test_a_fractional_shift_keeps_its_fraction(self) -> None:
        name = output_name(
            "song.wav", PitchTimeSettings(mode=MODE_PITCH, semitones=0.5)
        )

        assert name == "song_pitch_+0.5st.wav"
