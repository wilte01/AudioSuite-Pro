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


# ═════════════════════════════════════════════════════════════════════════════
# Golden-vector measurement (plan iteration 5, item F1 / audit #19)
# ═════════════════════════════════════════════════════════════════════════════
# The pre-existing suite above drives analyze_mood through _feature_stack,
# which patches the tempo/flux/zcr/centroid/lowband extractors *and* the key
# detector.  That proves the blend arithmetic given inputs, but nothing proves
# a real major-keyed signal is actually read as positive-valence -- the
# "asserted, not measured" gap this item exists to close.
#
# The vectors below run the whole chain on real audio: real librosa features,
# the real key_detector key vote, the real blend.  Ground truth is knowable by
# construction because the fixture's mode is a deliberate one-semitone change:
#
#   * major triad = root + M3 (4 semitones) + P5 (7)
#   * minor triad = root + m3 (3 semitones) + P5 (7)
#
# so a major/minor pair differs ONLY in the third's height and the resulting
# valence must differ in sign.  No commercial audio is involved; the fixtures
# are generated in-memory and redistributable under GPL-3.0.
#
# Measured at HEAD (recorded in the Completion Log): every major triad scored
# positive valence (+0.17 to +0.33) and every minor triad negative (-0.19 to
# -0.93); the assertion bands below are sign invariants derived from the mode
# semantics, with the numeric bands set from those measurements, not fitted.
# ═════════════════════════════════════════════════════════════════════════════

_MAJOR_THIRD = 4
_MINOR_THIRD = 3
_PERFECT_FIFTH = 7

# Measured at HEAD; order is meaningful (ascending valence is not claimed).
_MAJOR_TRIAD_ROOTS: tuple[int, ...] = (60, 65, 67, 62)  # C, F, G, D
_MINOR_TRIAD_ROOTS: tuple[int, ...] = (57, 62, 64, 59)  # A, D, E, B


def _triad(root_midi: int, third: int, seconds: float = 2.0) -> np.ndarray:
    """A triad of equal-amplitude sines (root, third, fifth), peak-normalised.

    Equal amplitudes keep the chroma vector symmetric about the root, so the
    detected mode reflects the constructed third rather than a voicing
    accident.
    """
    n = int(SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    signal = sum(
        np.sin(2.0 * np.pi * 440.0 * 2 ** ((root_midi + iv - 69) / 12.0) * t)
        for iv in (0, third, _PERFECT_FIFTH)
    )
    return (signal / np.max(np.abs(signal))).astype(np.float64)


def _major_triad(root_midi: int, seconds: float = 2.0) -> np.ndarray:
    return _triad(root_midi, _MAJOR_THIRD, seconds)


def _minor_triad(root_midi: int, seconds: float = 2.0) -> np.ndarray:
    return _triad(root_midi, _MINOR_THIRD, seconds)


def _noise_at_rms(rms: float, seed: int = 2024, seconds: float = 10.0) -> np.ndarray:
    """Seeded white noise rescaled to an exact RMS."""
    generator = np.random.default_rng(seed)
    noise = generator.standard_normal(int(SR * seconds))
    return (noise / np.sqrt(np.mean(np.square(noise))) * rms).astype(np.float64)


class TestGoldenVectorMeasuredValence:
    """Mode decides the valence sign, measured end-to-end on real audio."""

    @pytest.mark.parametrize("root_midi", _MAJOR_TRIAD_ROOTS)
    def test_major_triad_measures_positive_valence(self, root_midi: int) -> None:
        result = analyze_mood(_major_triad(root_midi), SR)
        assert result.valence > 0.0, (
            f"major triad on MIDI {root_midi} measured valence "
            f"{result.valence:+.4f}; a major mode must not read as negative"
        )
        assert 0.0 < result.valence <= 1.0
        assert len(result.mood_words) == 3
        assert "Grim" not in result.mood_words
        assert "Dreary" not in result.mood_words

    @pytest.mark.parametrize("root_midi", _MINOR_TRIAD_ROOTS)
    def test_minor_triad_measures_negative_valence(self, root_midi: int) -> None:
        result = analyze_mood(_minor_triad(root_midi), SR)
        assert result.valence < 0.0, (
            f"minor triad on MIDI {root_midi} measured valence "
            f"{result.valence:+.4f}; a minor mode must not read as positive"
        )
        assert -1.0 <= result.valence < 0.0
        assert len(result.mood_words) == 3
        assert "Energetic" not in result.mood_words
        assert "Playful" not in result.mood_words

    @pytest.mark.parametrize("root_midi", (60, 62, 64, 65, 67, 69))
    def test_only_the_third_differs_and_the_valence_sign_flips(
        self, root_midi: int
    ) -> None:
        """The paired vector: identical root and fifth, one semitone of
        third.  The mode vote -- not amplitude, length or sample rate -- is
        what moves the sign, which is the property the blend must preserve."""
        major = analyze_mood(_major_triad(root_midi), SR)
        minor = analyze_mood(_minor_triad(root_midi), SR)
        assert major.valence > 0.0 > minor.valence, (
            f"root MIDI {root_midi}: major {major.valence:+.4f} / "
            f"minor {minor.valence:+.4f} did not straddle zero"
        )

    def test_major_progression_reads_above_its_minor_counterpart(self) -> None:
        """C I-IV-V-I vs A i-VI-III-VI-i over the same bar length."""
        major_progression = np.concatenate([_major_triad(m) for m in (60, 65, 67, 60)])
        minor_progression = np.concatenate(
            [_minor_triad(m) for m in (57, 60, 65, 60, 57)]
        )
        major_result = analyze_mood(major_progression, SR)
        minor_result = analyze_mood(minor_progression, SR)
        assert major_result.valence > minor_result.valence, (
            f"C progression {major_result.valence:+.4f} did not exceed "
            f"Am progression {minor_result.valence:+.4f}"
        )


class TestGoldenVectorMeasuredArousal:
    """Level and the silence guard, measured end-to-end."""

    def test_arousal_increases_monotonically_with_loudness(self) -> None:
        """Same seeded noise at three levels: only RMS differs, so any
        arousal change is attributable to the RMS feature alone.

        Measured at HEAD: 0.2328 (RMS 0.05) < 0.4728 (0.2) < 0.6328 (0.5).
        The band is +/-0.02 around each measured value, and the ordering
        assertion is the real invariant.
        """
        quiet = analyze_mood(_noise_at_rms(0.05), SR)
        medium = analyze_mood(_noise_at_rms(0.2), SR)
        loud = analyze_mood(_noise_at_rms(0.5), SR)
        assert quiet.arousal < medium.arousal < loud.arousal, (
            f"arousal not monotonic in level: {quiet.arousal:.4f} / "
            f"{medium.arousal:.4f} / {loud.arousal:.4f}"
        )
        assert abs(quiet.arousal - 0.2328) <= 0.02
        assert abs(medium.arousal - 0.4728) <= 0.02
        assert abs(loud.arousal - 0.6328) <= 0.02
        # Level must not leak into valence: the spectrum is unchanged.
        assert abs(quiet.valence - medium.valence) <= 0.01
        assert abs(medium.valence - loud.valence) <= 0.01

    @pytest.mark.parametrize("rms", (0.5, 0.2, 0.05))
    def test_energy_band_tracks_the_loudness_ladder(self, rms: float) -> None:
        """Measured at HEAD: energy 5 / 4 / 4 for RMS 0.5 / 0.2 / 0.05 --
        the loudest level is the only one reaching the top band."""
        result = analyze_mood(_noise_at_rms(rms), SR)
        assert 1 <= result.energy <= 5
        if rms == 0.5:
            assert result.energy == 5

    def test_at_the_silence_threshold_the_signal_is_analysed(self) -> None:
        """The guard rejects RMS < 1e-4, so exactly 1e-4 must be accepted.

        This pins the boundary from the accepting side, complementing
        TestGuards (which only covers a clearly-silent signal).
        """
        at_threshold = _noise_at_rms(1.0e-4, seed=5, seconds=3.0)
        assert abs(float(np.sqrt(np.mean(np.square(at_threshold)))) - 1.0e-4) < 1e-9
        result = analyze_mood(at_threshold, SR)
        assert -1.0 <= result.valence <= 1.0
        assert -1.0 <= result.arousal <= 1.0
        assert 0.0 <= result.confidence <= 1.0

    def test_just_below_the_silence_threshold_it_raises(self) -> None:
        """The rejecting side of the same boundary, one part in 10^4 below."""
        just_below = _noise_at_rms(9.9e-5, seed=5, seconds=3.0)
        assert float(np.sqrt(np.mean(np.square(just_below)))) < 1.0e-4
        with pytest.raises(AudioAnalysisError, match="near-silent"):
            analyze_mood(just_below, SR)


class TestGoldenVectorReproducibility:
    def test_identical_input_measures_identical_output(self) -> None:
        signal = _major_triad(60)
        first = analyze_mood(signal, SR)
        second = analyze_mood(signal, SR)
        assert first == second

    def test_seeded_noise_is_bit_reproducible(self) -> None:
        assert np.array_equal(_noise_at_rms(0.2), _noise_at_rms(0.2))
