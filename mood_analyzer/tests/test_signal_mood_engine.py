"""
tests/test_signal_mood_engine.py
Tests for mood_analyzer.core.signal_mood_engine.

Covers:
  - guards: empty / near-silent signals raise AudioAnalysisError
  - deterministic feature-blend behaviour (high-valence/high-arousal major-fast
    vs low-valence/low-arousal minor-slow) via source-module patches
  - output invariants: mood_words length 3, distinct, semicolon tag string,
    confidence and energy bands in range
  - a real-librosa smoke test on synthetic audio
"""

from contextlib import ExitStack
from unittest.mock import patch

import numpy as np
import pytest

from audio_suite_shared.exceptions import AudioAnalysisError
from mood_analyzer.core.signal_mood_engine import (
    MoodAnalysis,
    _arousal_band,
    _assign_energy_band,
    _mode_to_valence,
    _normalise,
    _valence_band,
    analyze_mood,
)

MODULE = "mood_analyzer.core.signal_mood_engine"

SR = 22050


def _sine(
    amplitude: float = 0.707, freq: float = 440.0, seconds: float = 1.0
) -> np.ndarray:
    """A sine tone with a known RMS (amplitude / sqrt(2))."""
    t = np.linspace(0.0, seconds, int(SR * seconds), endpoint=False)
    return amplitude * np.sin(2.0 * np.pi * freq * t)


class TestGuards:
    def test_empty_signal_raises(self) -> None:
        with pytest.raises(AudioAnalysisError):
            analyze_mood(np.array([], dtype=np.float64), SR)

    def test_near_silent_signal_raises(self) -> None:
        y = np.zeros(SR, dtype=np.float64)
        with pytest.raises(AudioAnalysisError):
            analyze_mood(y, SR)


class TestFeatureMappings:
    def test_normalise_maps_lo_hi_to_negative_positive(self) -> None:
        assert _normalise(0.0, 0.0, 1.0) == -1.0
        assert _normalise(1.0, 0.0, 1.0) == 1.0
        assert _normalise(0.5, 0.0, 1.0) == 0.0

    def test_normalise_clips_out_of_range(self) -> None:
        assert _normalise(10.0, 0.0, 1.0) == 1.0
        assert _normalise(-5.0, 0.0, 1.0) == -1.0

    def test_mode_to_valence_positive_for_major(self) -> None:
        assert _mode_to_valence("D", 1.0) > 0.0

    def test_mode_to_valence_negative_for_minor(self) -> None:
        assert _mode_to_valence("Am", 1.0) < 0.0

    def test_mode_to_valence_scaled_by_strength(self) -> None:
        assert abs(_mode_to_valence("D", 0.5)) < abs(_mode_to_valence("D", 1.0))

    def test_bands_respect_bounds(self) -> None:
        assert _valence_band(1.0) == 3
        assert _valence_band(-1.0) == 0
        assert _arousal_band(1.0) == 3
        assert _arousal_band(-1.0) == 0

    def test_energy_band_in_1_to_6(self) -> None:
        assert 1 <= _assign_energy_band(-1.0) <= 6
        assert 1 <= _assign_energy_band(0.0) <= 6
        assert 1 <= _assign_energy_band(1.0) <= 6


class TestMoodAnalysisContract:
    def test_to_tag_string_semicolon_joined(self) -> None:
        m = MoodAnalysis(
            valence=0.7,
            arousal=0.7,
            mood_words=("Energetic", "Bright", "Confident"),
            confidence=0.9,
            energy=5,
        )
        assert m.to_tag_string() == "Energetic;Bright;Confident"

    def test_mood_words_capacity(self) -> None:
        m = MoodAnalysis(
            valence=0.0,
            arousal=0.0,
            mood_words=("Peaceful", "Tender", "Reflective"),
            confidence=0.5,
            energy=3,
        )
        assert len(m.mood_words) == 3


class TestAnalyzeMoodDeterministic:
    """Feature blend is verified with deterministic mocked features.

    Individual ``patch`` contexts are combined via an ExitStack so that
    module-level names (``_mean_flux`` etc.), ``librosa.beat.beat_track``
    and the key engine are all stubbed at once.
    """

    def _feature_stack(self, **feature_values) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            patch(
                "librosa.beat.beat_track",
                new=lambda y, sr: (
                    feature_values.get("tempo", 120.0),
                    [],
                ),
            )
        )
        stack.enter_context(
            patch(
                f"{MODULE}._mean_flux",
                new=lambda y, sr: feature_values.get("flux", 0.05),
            )
        )
        stack.enter_context(
            patch(
                f"{MODULE}._mean_zcr",
                new=lambda y: feature_values.get("zcr", 0.08),
            )
        )
        stack.enter_context(
            patch(
                f"{MODULE}._mean_centroid",
                new=lambda y, sr: feature_values.get("centroid", 2800.0),
            )
        )
        stack.enter_context(
            patch(
                f"{MODULE}._lowband_energy",
                new=lambda y, sr: feature_values.get("lowband", 0.35),
            )
        )
        stack.enter_context(
            patch(
                "key_detector.core.key_engine.detect_key_with_strength",
                new=lambda y, sr: (
                    feature_values.get("key", "C"),
                    feature_values.get("key_strength", 0.9),
                ),
            )
        )
        return stack

    @pytest.mark.parametrize(
        "feature_values",
        [
            {
                "tempo": 140.0,
                "flux": 0.2,
                "zcr": 0.2,
                "centroid": 4000.0,
                "lowband": 0.1,
                "key": "D",
                "key_strength": 0.9,
            },
            {
                "tempo": 170.0,
                "flux": 0.2,
                "zcr": 0.2,
                "centroid": 5000.0,
                "lowband": 0.1,
                "key": "G",
                "key_strength": 1.0,
            },
        ],
    )
    def test_major_fast_signal_scores_high_valence_and_arousal(
        self, feature_values
    ) -> None:
        y = _sine(amplitude=0.707)
        with self._feature_stack(**feature_values):
            m = analyze_mood(y, SR)
        assert m.valence > 0.6
        assert m.arousal > 0.6
        assert m.mood_words[0] == "Energetic"

    @pytest.mark.parametrize(
        "feature_values",
        [
            {
                "tempo": 60.0,
                "flux": 0.005,
                "zcr": 0.01,
                "centroid": 400.0,
                "lowband": 0.6,
                "key": "Am",
                "key_strength": 0.9,
            },
            {
                "tempo": 70.0,
                "flux": 0.005,
                "zcr": 0.01,
                "centroid": 300.0,
                "lowband": 0.8,
                "key": "Em",
                "key_strength": 1.0,
            },
        ],
    )
    def test_minor_slow_signal_scores_low_valence_and_arousal(
        self, feature_values
    ) -> None:
        y = _sine(amplitude=0.02)
        with self._feature_stack(**feature_values):
            m = analyze_mood(y, SR)
        assert m.valence < -0.7
        assert m.arousal < -0.9
        assert m.mood_words[0] == "Dreary"

    def test_confidence_within_bounds(self) -> None:
        y = _sine(amplitude=0.707)
        with self._feature_stack():
            m = analyze_mood(y, SR)
        assert 0.1 <= m.confidence <= 1.0

    def test_energy_band_in_range(self) -> None:
        y = _sine(amplitude=0.707)
        with self._feature_stack():
            m = analyze_mood(y, SR)
        assert 1 <= m.energy <= 6


class TestAnalyzeMoodLibrosaSmoke:
    """End-to-end smoke test against real librosa on synthetic audio.

    Only checks that a non-silent signal produces a valid MoodAnalysis
    without crashing; exact words are a blend outcome, not an invariant.
    """

    def test_real_librosa_runs_on_synthetic_audio(self) -> None:
        rng = np.random.default_rng(7)
        y = 0.2 * rng.standard_normal(SR)
        m = analyze_mood(y, SR)
        assert isinstance(m, MoodAnalysis)
        assert len(m.mood_words) == 3
        assert len(set(m.mood_words)) == len(m.mood_words)
        assert 0.1 <= m.confidence <= 1.0
        assert 1 <= m.energy <= 6


class TestValenceHemisphereIsolation:
    """Verify that secondary and tertiary mood descriptors strictly preserve
    valence polarity."""

    NEGATIVE_WORDS = {
        "Dreary",
        "Melancholic",
        "Grim",
        "Somber",
        "Restless",
        "Pensive",
        "Tense",
        "Driving",
    }
    POSITIVE_WORDS = {
        "Reflective",
        "Serene",
        "Peaceful",
        "Tender",
        "Hopeful",
        "Warm",
        "Playful",
        "Energetic",
    }

    def test_negative_words_only_contain_negative_neighbors(self) -> None:
        from mood_analyzer.core.signal_mood_engine import _MOOD_RANKING

        for word in self.NEGATIVE_WORDS:
            ranking = _MOOD_RANKING[word]
            for neighbor in ranking:
                assert neighbor in self.NEGATIVE_WORDS, (
                    f"Negative word '{word}' contains positive neighbor '{neighbor}'"
                )

    def test_positive_words_only_contain_positive_neighbors(self) -> None:
        from mood_analyzer.core.signal_mood_engine import _MOOD_RANKING

        for word in self.POSITIVE_WORDS:
            ranking = _MOOD_RANKING[word]
            for neighbor in ranking:
                assert neighbor in self.POSITIVE_WORDS, (
                    f"Positive word '{word}' contains negative neighbor '{neighbor}'"
                )

    def test_col_1_driving_top_words_are_coherent(self) -> None:
        from mood_analyzer.core.signal_mood_engine import _rank_mood_words

        # v_idx=1 (mild negative), a_idx=3 (high arousal) -> winner is Driving
        words = _rank_mood_words(v_idx=1, a_idx=3)
        assert words == ("Driving", "Tense", "Pensive")
        assert "Playful" not in words

    def test_col_1_somber_top_words_are_coherent(self) -> None:
        from mood_analyzer.core.signal_mood_engine import _rank_mood_words

        # v_idx=1 (mild negative), a_idx=1 (low-mid arousal) -> winner is Somber
        words = _rank_mood_words(v_idx=1, a_idx=1)
        assert words == ("Somber", "Grim", "Melancholic")
        assert "Peaceful" not in words
