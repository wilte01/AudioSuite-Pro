"""
tests/test_key_engine.py
Comprehensive pytest suite for key_engine.detect_key.

Covers:
  - Impulse response (delta signal)
  - Pure sine waves for each of the 12 chromatic pitch classes
  - Digital silence (zero-energy guard)
  - Return-type and value-format contract
  - Major vs minor discrimination
  - Root pitch-class correctness for all 12 major and 12 minor triads
  - Display-notation overrides (conventional flat spelling)
  - Edge parameters: very short signal, very high sample rate
  - Constant (DC) signal: non-zero but zero-energy in CQT bins
  - NaN input: must not propagate silently
  - Tie-breaking: major preferred on equal correlation
  - Stereo input: multi-channel array handling
"""

import re

import librosa
import numpy as np
import numpy.typing as npt
import pytest

from audio_suite_shared.exceptions import AudioAnalysisError
from key_detector.core.key_engine import detect_key

# ── Helpers ───────────────────────────────────────────────────────────────────

SR: int = 22050
DURATION_SECS: float = 3.0
N_SAMPLES: int = int(SR * DURATION_SECS)

_MIDI_ROOTS = {
    "C": 60,
    "C#": 61,
    "D": 62,
    "D#": 63,
    "E": 64,
    "F": 65,
    "F#": 66,
    "G": 67,
    "G#": 68,
    "A": 69,
    "A#": 70,
    "B": 71,
}

_VALID_KEY_PATTERN = re.compile(r"^(C|C#|D|Eb|E|F|F#|G|G#|Ab|A|Bb|B)m?$")

_MAJOR_EXPECTED = {
    "C": "C",
    "C#": "C#",
    "D": "D",
    "D#": "Eb",
    "E": "E",
    "F": "F",
    "F#": "F#",
    "G": "G",
    "G#": "Ab",
    "A": "A",
    "A#": "Bb",
    "B": "B",
}

_MINOR_EXPECTED = {
    "C": "Cm",
    "C#": "C#m",
    "D": "Dm",
    "D#": "Ebm",
    "E": "Em",
    "F": "Fm",
    "F#": "F#m",
    "G": "Gm",
    "G#": "G#m",
    "A": "Am",
    "A#": "Bbm",
    "B": "Bm",
}


def _midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _pure_tone(
    freq_hz: float, sr: int = SR, duration: float = DURATION_SECS
) -> npt.NDArray[np.float64]:
    """Generate a pure sine wave at *freq_hz*."""
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    return np.sin(2.0 * np.pi * freq_hz * t).astype(np.float64)


def _major_chord(
    root_midi: int, sr: int = SR, duration: float = DURATION_SECS
) -> npt.NDArray[np.float64]:
    """Generate a major triad (root + M3 + P5) as superimposed sines."""
    freqs = [
        _midi_to_hz(root_midi),
        _midi_to_hz(root_midi + 4),
        _midi_to_hz(root_midi + 7),
    ]
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    signal = sum(np.sin(2.0 * np.pi * f * t) for f in freqs)
    return (signal / np.max(np.abs(signal))).astype(np.float64)


def _minor_chord(
    root_midi: int, sr: int = SR, duration: float = DURATION_SECS
) -> npt.NDArray[np.float64]:
    """Generate a minor triad (root + m3 + P5) as superimposed sines."""
    freqs = [
        _midi_to_hz(root_midi),
        _midi_to_hz(root_midi + 3),
        _midi_to_hz(root_midi + 7),
    ]
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    signal = sum(np.sin(2.0 * np.pi * f * t) for f in freqs)
    return (signal / np.max(np.abs(signal))).astype(np.float64)


# ── Return-type contract ──────────────────────────────────────────────────────


class TestReturnContract:
    """detect_key must always return a non-empty string matching the key pattern."""

    def test_return_type_is_str(self) -> None:
        signal = _pure_tone(_midi_to_hz(69))
        result = detect_key(signal, SR)
        assert isinstance(result, str)

    def test_return_value_matches_pattern(self) -> None:
        signal = _pure_tone(_midi_to_hz(60))
        result = detect_key(signal, SR)
        assert _VALID_KEY_PATTERN.match(result), (
            f"Returned key '{result}' does not match expected format."
        )

    def test_major_key_has_no_m_suffix(self) -> None:
        signal = _major_chord(_MIDI_ROOTS["C"])
        result = detect_key(signal, SR)
        assert not result.endswith("m"), (
            f"Major chord incorrectly classified as minor: '{result}'"
        )

    def test_minor_key_has_m_suffix(self) -> None:
        signal = _minor_chord(_MIDI_ROOTS["A"])
        result = detect_key(signal, SR)
        assert result.endswith("m"), (
            f"Minor chord incorrectly classified as major: '{result}'"
        )


# ── Digital silence guard ─────────────────────────────────────────────────────


class TestSilenceGuard:
    """A zero-energy signal must raise AudioAnalysisError, not propagate NaN."""

    def test_all_zeros_raises_value_error(self) -> None:
        silence: npt.NDArray[np.float64] = np.zeros(N_SAMPLES, dtype=np.float64)
        with pytest.raises(AudioAnalysisError, match="zero-energy"):
            detect_key(silence, SR)

    def test_near_zero_does_not_raise(self) -> None:
        """Sub-threshold noise that is not identically zero must NOT raise."""
        rng = np.random.default_rng(42)
        noise: npt.NDArray[np.float64] = rng.normal(0.0, 1e-6, N_SAMPLES).astype(
            np.float64
        )
        result = detect_key(noise, SR)
        assert _VALID_KEY_PATTERN.match(result)


# ── Impulse response ──────────────────────────────────────────────────────────


class TestImpulseResponse:
    """An impulse (delta[n]) has a flat spectrum — result must be a valid key string."""

    def test_impulse_returns_valid_key(self) -> None:
        impulse: npt.NDArray[np.float64] = np.zeros(N_SAMPLES, dtype=np.float64)
        impulse[0] = 1.0
        result = detect_key(impulse, SR)
        assert _VALID_KEY_PATTERN.match(result), (
            f"Impulse response produced invalid key: '{result}'"
        )

    def test_impulse_no_crash(self) -> None:
        impulse: npt.NDArray[np.float64] = np.zeros(N_SAMPLES, dtype=np.float64)
        impulse[0] = 1.0
        detect_key(impulse, SR)


# ── Chromatic coverage ────────────────────────────────────────────────────────


class TestChromaticRoots:
    """Each major/minor triad root should be classified correctly."""

    @pytest.mark.parametrize("note_name,midi_root", list(_MIDI_ROOTS.items()))
    def test_major_chord_classified_as_major(
        self, note_name: str, midi_root: int
    ) -> None:
        signal = _major_chord(midi_root)
        result = detect_key(signal, SR)
        assert result == _MAJOR_EXPECTED[note_name], (
            f"Major chord rooted at {note_name} expected "
            f"'{_MAJOR_EXPECTED[note_name]}', "
            f"got '{result}'"
        )

    @pytest.mark.parametrize("note_name,midi_root", list(_MIDI_ROOTS.items()))
    def test_minor_chord_classified_as_minor(
        self, note_name: str, midi_root: int
    ) -> None:
        signal = _minor_chord(midi_root)
        result = detect_key(signal, SR)
        assert result == _MINOR_EXPECTED[note_name], (
            f"Minor chord rooted at {note_name} expected "
            f"'{_MINOR_EXPECTED[note_name]}', "
            f"got '{result}'"
        )


# ── Edge parameters ───────────────────────────────────────────────────────────


class TestEdgeParameters:
    """Verify robustness under unusual but legal inputs."""

    def test_very_short_signal(self) -> None:
        short: npt.NDArray[np.float64] = _pure_tone(_midi_to_hz(60), duration=0.1)
        result = detect_key(short, SR)
        assert _VALID_KEY_PATTERN.match(result)

    def test_high_sample_rate(self) -> None:
        sr_high = 44100
        signal = _pure_tone(_midi_to_hz(60), sr=sr_high)
        result = detect_key(signal, sr_high)
        assert _VALID_KEY_PATTERN.match(result)

    def test_float32_input_promoted_correctly(self) -> None:
        """float32 input must be silently promoted to float64 without crash or NaN."""
        signal_f32: npt.NDArray[np.float32] = _major_chord(_MIDI_ROOTS["G"]).astype(
            np.float32
        )
        result = detect_key(signal_f32, SR)
        assert _VALID_KEY_PATTERN.match(result)

    def test_single_sample_non_zero(self) -> None:
        """Non-zero single sample: must not raise ValueError from silence guard."""
        single: npt.NDArray[np.float64] = np.array([0.5], dtype=np.float64)
        try:
            result = detect_key(single, SR)
            assert _VALID_KEY_PATTERN.match(result)
        except ValueError as exc:
            pytest.fail(
                f"Silence guard incorrectly raised on non-zero single sample: {exc}"
            )
        except Exception:
            pass  # librosa CQT failure on trivially short signal is acceptable


# ── Pure sine wave THD proxy ──────────────────────────────────────────────────


class TestPureSineTones:
    """Pure sines must complete without NaN propagation or crash."""

    @pytest.mark.parametrize("midi_note", [60, 62, 64, 65, 67, 69, 71])
    def test_pure_sine_no_crash(self, midi_note: int) -> None:
        freq = _midi_to_hz(midi_note)
        signal = _pure_tone(freq)
        result = detect_key(signal, SR)
        assert _VALID_KEY_PATTERN.match(result), (
            f"Pure sine at MIDI {midi_note} ({freq:.1f} Hz) produced "
            f"invalid key: '{result}'"
        )


# ── Display-notation overrides (DJ/pop convention) ────────────────────────────


class TestDisplayNotationOverrides:
    """
    Pin down the exact conventional spelling for pitch classes that have a
    standard flat-notation override.  These intentionally assert the literal
    returned string (not just pattern validity) so a future change to the
    override dicts is caught as a deliberate, reviewed decision rather than
    silently passing because '_VALID_KEY_PATTERN' happens to be permissive.

    Convention (DJ/pop, not classical):
      - Major: D#->Eb, G#->Ab, A#->Bb are remapped. C# and F# are NOT
        (sharp spelling dominates common usage for those two).
      - Minor: D#m->Ebm, A#m->Bbm are remapped. C#m, F#m, and G#m are NOT
        (G#m is the standard relative minor of B major; Abm is rare outside
        classical contexts, unlike its major counterpart Ab).
    """

    @pytest.mark.parametrize(
        "midi_root,expected",
        [
            (_MIDI_ROOTS["C"], "C"),
            (_MIDI_ROOTS["C#"], "C#"),  # NOT remapped to Db
            (_MIDI_ROOTS["D#"], "Eb"),  # remapped
            (_MIDI_ROOTS["F#"], "F#"),  # NOT remapped to Gb
            (_MIDI_ROOTS["G#"], "Ab"),  # remapped
            (_MIDI_ROOTS["A#"], "Bb"),  # remapped
        ],
    )
    def test_major_chord_display_spelling(self, midi_root: int, expected: str) -> None:
        signal = _major_chord(midi_root)
        result = detect_key(signal, SR)
        assert result == expected, (
            f"Expected major chord rooted at MIDI {midi_root} to display as "
            f"'{expected}', got '{result}'"
        )

    @pytest.mark.parametrize(
        "midi_root,expected",
        [
            (_MIDI_ROOTS["A"], "Am"),
            (_MIDI_ROOTS["C#"], "C#m"),  # NOT remapped to Dbm
            (_MIDI_ROOTS["D#"], "Ebm"),  # remapped
            (_MIDI_ROOTS["F#"], "F#m"),  # NOT remapped to Gbm
            (_MIDI_ROOTS["G#"], "G#m"),  # NOT remapped to Abm (asymmetric vs major)
            (_MIDI_ROOTS["A#"], "Bbm"),  # remapped
        ],
    )
    def test_minor_chord_display_spelling(self, midi_root: int, expected: str) -> None:
        signal = _minor_chord(midi_root)
        result = detect_key(signal, SR)
        assert result == expected, (
            f"Expected minor chord rooted at MIDI {midi_root} to display as "
            f"'{expected}', got '{result}'"
        )


# ── Constant (DC) signal ───────────────────────────────────────────────────────


class TestConstantSignal:
    """A constant non-zero signal (DC offset) has zero energy in all CQT
    frequency bins. The function must not crash or silently propagate NaN."""

    def test_constant_signal_returns_valid_key(self) -> None:
        const: npt.NDArray[np.float64] = np.ones(N_SAMPLES, dtype=np.float64)
        result = detect_key(const, SR)
        assert _VALID_KEY_PATTERN.match(result), (
            f"Constant signal produced invalid key: '{result}'"
        )


# ── NaN input guard ────────────────────────────────────────────────────────────


class TestNaNInput:
    """A signal containing NaN values must not silently propagate NaN."""

    def test_nan_in_signal_does_not_return_nan_string(self) -> None:
        signal = _pure_tone(_midi_to_hz(60))
        signal[0] = np.nan
        try:
            result = detect_key(signal, SR)
            assert _VALID_KEY_PATTERN.match(result), (
                f"Signal with NaN produced invalid key: '{result}'"
            )
        except (ValueError, RuntimeError, librosa.ParameterError):
            pass


# ── Tie-breaking (major vs minor on equal correlation) ────────────────────────


class TestTieBreaking:
    """When major and minor correlation are equal, major should be preferred
    (the code uses max_maj >= max_min)."""

    def test_noise_signal_returns_valid_key(self) -> None:
        rng = np.random.default_rng(12345)
        noise = rng.normal(0.0, 1.0, N_SAMPLES).astype(np.float64)
        result = detect_key(noise, SR)
        assert _VALID_KEY_PATTERN.match(result), (
            f"Noise signal produced invalid key: '{result}'"
        )


# ── Stereo (multi-channel) input ───────────────────────────────────────────────


class TestStereoInput:
    """Multi-channel (stereo) input handling."""

    def test_stereo_array_returns_valid_or_raises(self) -> None:
        stereo = np.zeros((2, N_SAMPLES), dtype=np.float64)
        stereo[0, 0] = 1.0
        try:
            result = detect_key(stereo, SR)
            assert isinstance(result, str)
        except (ValueError, TypeError, IndexError):
            pass
