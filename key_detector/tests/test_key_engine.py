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
  - F3 tonality gate: a clearly tonal centre is named even when the modal
    vote is ambiguous (the real-music calibration that triggered F3)
  - NaN input: must not propagate silently
  - Tie-breaking: major preferred on equal correlation
  - Stereo input: multi-channel array handling

Changed in 1.0.1: adds coverage for the recalibrated keyless fallback.
Changed in 2.7.0: `TestRealMusicKeyCorpus` measures the detector on the
CC0 Bach corpus (34 preludes and fugues) and locks 20/34 accuracy, the miss
pattern, the tonic-disjoint split and the fact that neither gate threshold
can repair a miss (D147, D154).
Changed in 2.7.0: `TestAtonalNoiseFloor` pins seeded brown and band-limited
noise under `CLARITY_FLOOR`, with the 3 s and narrow-band limits it cannot
cover recorded in the class docstring (D149).
Changed in 2.7.0: `TestHarmonicSecondPass` locks the percussion-removed
second pass and its own floor (D151).
"""

import re
import wave
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt
import pytest

from audio_suite_shared.analysis_loader import (
    is_effectively_silent,
    load_analysis_audio,
)
from audio_suite_shared.exceptions import AudioAnalysisError
from key_detector.core.key_engine import (
    CLARITY_FLOOR,
    DEFAULT_CORRELATION,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    DEFAULT_WEIGHTING,
    HARMONIC_CLARITY_FLOOR,
    UNKNOWN_KEY,
    _harmonic_pass,
    _pitch_class_profile,
    _score_profile,
    analyze_key,
    detect_key,
    detect_key_with_strength,
)
from tests.corpus_table import pipe_rows

# ── Helpers ───────────────────────────────────────────────────────────────────

SR: int = 22050
DURATION_SECS: float = 3.0
N_SAMPLES: int = int(SR * DURATION_SECS)

#: Window the noise fixtures are generated at.  The engine analyses up to
#: ``DEFAULT_ANALYSIS_SECONDS`` (90 s), but 3 s - the length of the triad
#: fixtures - is too short for a stable coloured-noise measurement: across ten
#: seeds, 3 s of brown noise spans 0.020-0.038 clarity and one seed crosses
#: ``CLARITY_FLOOR``, while the same seeds at 20 s span 0.020-0.027 and none do.
#: The variance is the short window's, not the gate's, so the fixtures use the
#: length a real file is analysed at rather than a length that manufactures a
#: crossing (D149).
_ATONAL_SECONDS: float = 20.0

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


def _assert_key_or_fallback(result: str, context: str) -> None:
    """Assert *result* is a well-formed outcome for untuned material.

    Since plan iteration 5 item F2, material with no defensible key (silence
    residue, impulses, DC offset, white noise) is reported as
    :data:`UNKNOWN_KEY` instead of a fabricated key. Robustness tests over
    such material assert *this* domain: a real key name or the documented
    fallback, never NaN, never a crash.
    """
    assert _VALID_KEY_PATTERN.match(result) or result == UNKNOWN_KEY, (
        f"{context} produced neither a valid key nor the documented "
        f"fallback: '{result}'"
    )


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


def _white_noise(seed: int) -> npt.NDArray[np.float64]:
    """Seeded unit-variance broadband noise: the atonal F2 negative vector."""
    return np.random.default_rng(seed).normal(0.0, 1.0, N_SAMPLES).astype(np.float64)


def _brown_noise(
    seed: int, seconds: float = _ATONAL_SECONDS
) -> npt.NDArray[np.float64]:
    """Seeded detrended-brown noise: the low-frequency rumble case.

    Same generator as ``bpm_analyzer/tests/test_bpm_detector.py`` (a ``cumsum``
    of white noise, linearly detrended, scaled to 0.5) so one noise colour means
    the same thing in both analysis suites.
    """
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    walk = np.cumsum(rng.standard_normal(n))
    walk -= np.linspace(walk[0], walk[-1], n)
    return (walk / np.max(np.abs(walk)) * 0.5).astype(np.float64)


def _band_limited_noise(
    seed: int, low_hz: float, high_hz: float, seconds: float = _ATONAL_SECONDS
) -> npt.NDArray[np.float64]:
    """Seeded white noise with every frequency outside *low_hz*-*high_hz* removed."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs: npt.NDArray[np.float64] = np.fft.rfftfreq(n, 1 / SR)
    spectrum[(freqs < low_hz) | (freqs > high_hz)] = 0.0
    signal: npt.NDArray[np.float64] = np.fft.irfft(spectrum, n)
    return (signal / np.max(np.abs(signal)) * 0.5).astype(np.float64)


def _noisy_triad(
    root_midi: int, noise_amp: float = 0.8, seed: int = 42
) -> npt.NDArray[np.float64]:
    """A major triad buried in seeded broadband noise.

    The F3 regression vector (2026-10): a clearly tonal chord whose vote is
    made ambiguous by the noise, so the margin confidence lands near 0.08 —
    far below the 0.25 threshold — while the tonal clarity stays well above
    :data:`CLARITY_FLOOR`. That is the profile the F3 report measured on
    real recordings (seven of twelve tracks at margins of 0.001-0.015 with
    clear tonal centres), and it is exactly the case a margin-only fallback
    gate could never name — the defect F3 fixed.
    """
    noisy = _major_chord(root_midi) + noise_amp * _white_noise(seed)
    return (noisy / np.max(np.abs(noisy))).astype(np.float64)


def _write_wav(path: Path, y: npt.NDArray[np.float64], sr: int = SR) -> None:
    """Write a 16-bit mono PCM WAV (values clipped to +/-1)."""
    pcm_bytes = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm_bytes)


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
        _assert_key_or_fallback(result, "Near-zero noise")


# ── Impulse response ──────────────────────────────────────────────────────────


class TestImpulseResponse:
    """An impulse (delta[n]) has a flat spectrum — result must be a valid key string."""

    def test_impulse_returns_valid_key(self) -> None:
        impulse: npt.NDArray[np.float64] = np.zeros(N_SAMPLES, dtype=np.float64)
        impulse[0] = 1.0
        result = detect_key(impulse, SR)
        _assert_key_or_fallback(result, "Impulse response")

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
        _assert_key_or_fallback(result, "0.1s signal")

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
        _assert_key_or_fallback(result, "Constant signal")


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
        _assert_key_or_fallback(result, "Noise signal")


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


# ═════════════════════════════════════════════════════════════════════════════
# Golden-vector measurement (plan iteration 5, item F1 / audit #19)
# ═════════════════════════════════════════════════════════════════════════════
# These cases assert the *measured outcome* — that the detected key equals
# the key constructed into the fixture — not merely that a well-shaped value
# came back.  Ground truth is knowable by construction; no commercial audio
# is used, so the fixtures are unambiguously redistributable.
#
# Fixture provenance (recorded in the Completion Log):
#   * Every fixture below is generated in-memory with a seeded
#     `numpy.random.default_rng`, so two runs produce identical signals
#     (byte-reproducible by construction; asserted by the determinism test).
#   * Tolerances are declared from the construction (which pitch classes the
#     signal contains, plus the published K-S profile semantics), NOT fitted
#     to engine output; the current engine satisfied them at HEAD, which is
#     the before/after lock item F2 needs.
# ═════════════════════════════════════════════════════════════════════════════


def _dyad_signal(fundamental_midi: int) -> npt.NDArray[np.float64]:
    """A pure sine at a known fundamental plus its perfect fifth (0.5x)."""
    signal = (
        _pure_tone(_midi_to_hz(fundamental_midi))
        + _pure_tone(_midi_to_hz(fundamental_midi + 7)) * 0.5
    )
    return (signal / np.max(np.abs(signal))).astype(np.float64)


# ═════════════════════════════════════════════════════════════════════════════
# Real-material before/after measurement (plan iteration 5, item F2)
# ═════════════════════════════════════════════════════════════════════════════


def _harmonic_tone(
    fundamental_midi: int, sr: int, duration: float
) -> npt.NDArray[np.float64]:
    """An overtone-rich sustained tone (sawtooth-like partial series).

    A pure sine is the single most favourable input for chroma correlation:
    it occupies exactly one CQT bin. Real instrumental material smears energy
    across partials, so the reference excerpt below is built from this partial
    series rather than from sines, giving the detector the same kind of
    broadband harmonic context it meets in practice.
    """
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    fundamental = _midi_to_hz(fundamental_midi)
    tone = np.zeros_like(t)
    for partial, amplitude in enumerate((1.0, 0.5, 0.33, 0.25, 0.2, 0.16), start=1):
        tone += amplitude * np.sin(2.0 * np.pi * fundamental * partial * t)
    # Gentle attack/release so note onsets are realistic.
    envelope = np.minimum(1.0, np.minimum(t / 0.02, (duration - t) / 0.05))
    return (tone * np.maximum(envelope, 0.0)).astype(np.float64)


def _reference_excerpt() -> npt.NDArray[np.float64]:
    """A short I-IV-V-I passage in C major, as a multi-voice excerpt.

    Carries a bass line (root of each chord, one octave down) under an
    overtone-rich triad, at a musical tempo, so the pitch-class content is
    distributed across frames the way a recording's is rather than sitting in
    one static block.

    Ground truth: C major. Measured confidences are asserted below; see the
    Stage 5 decision log for the before/after table.
    """
    sr = SR
    note_seconds = 0.75
    passages: list[tuple[int, ...]] = [
        (48, 60, 64, 67),  # I   - bass C3, C-E-G
        (53, 57, 60, 64),  # IV  - bass F3, F-A-C
        (55, 59, 62, 67),  # V   - bass G3, G-B-D
        (48, 60, 64, 72),  # I   - bass C3, C-E-G (5th up top)
    ]
    chunks: list[npt.NDArray[np.float64]] = []
    for chord in passages:
        bass, *upper = chord
        voice = _harmonic_tone(bass, sr, note_seconds) * 0.55
        for midi in upper:
            voice = voice + _harmonic_tone(midi, sr, note_seconds) * 0.30
        chunks.append(voice)
    excerpt = np.concatenate(chunks)
    return (excerpt / np.max(np.abs(excerpt)) * 0.89).astype(np.float64)


class TestRealMaterialBeforeAfter:
    """Measure the same real-material excerpt under both scoring paths.

    F2's requirement is a before/after on material that goes through the real
    decode path, with a confidence recorded for each. "Before" is the legacy
    ``"pearson"`` scoring the suite shipped; "after" is the new default
    cosine scoring with its stated confidence.

    Note on the material: no commercial or third-party recording is used
    anywhere in this suite (F1's explicit constraint), and no recording ships
    with librosa, so the excerpt is a constructed, overtone-rich, multi-voice
    passage written to a real 16-bit PCM WAV and read back through
    ``analysis_loader`` — the same decode path the tool itself uses. The
    measurement is of the decoded audio, not of the engine's own state.
    """

    def test_excerpt_is_read_through_the_real_decoder(self, tmp_path: Path) -> None:
        path = tmp_path / "reference_excerpt.wav"
        _write_wav(path, _reference_excerpt())
        y, sr = load_analysis_audio(str(path))
        assert sr == SR
        assert y.size > 0
        assert not is_effectively_silent(y)

    def test_before_and_after_are_recorded_with_a_confidence(
        self, tmp_path: Path
    ) -> None:
        """The before/after evidence item F2 requires, measured on the decoded
        excerpt above.

        Tonal passage (ground truth C major), both paths:

        ==========  ====  ===========  ==============  ==================
        path        key   margin       confidence      low confidence?
        ==========  ====  ===========  ==============  ==================
        pearson     C     0.3765       1.0000          no
        cosine      C     0.0979       1.0000          no
        ==========  ====  ===========  ==============  ==================

        Both resolve the ground-truth key and both saturate, so clean tonal
        material is not regressed. The margin column is the informative
        change: cosine measures a far smaller margin for the same audio (it
        ignores overall magnitude, which Pearson folds in), which is why the
        two methods need different :data:`_MARGIN_SCALE` constants.

        Broadband noise, same decode path — the case F2 exists to fix
        (re-measured under the F3 DC centring):

        ==========  =============  ==============  ==================
        path        margin         confidence      result
        ==========  =============  ==============  ==================
        pearson     0.0459         0.2293          'Unknown'
        cosine      0.0015         0.0188          'Unknown'
        ==========  =============  ==============  ==================

        Pearson clears the fallback on the decoded path, but only by 0.019,
        and that is not a stable margin. Across the four raw-array noise
        seeds (see the noise vector in ``TestGoldenVectorNegative``) Pearson
        reports confidences of 0.8995 ('Em'), 0.2314, 0.6565 ('C#m') and
        0.1450 — i.e. for two of four seeds of pure white noise it fabricates
        a key and calls it confident, where cosine falls back on all four with
        confidences of 0.0089-0.0306. That measured fragility is why cosine
        is the default and why Pearson is documented as retained for
        compatibility rather than recommended.
        """
        path = tmp_path / "reference_excerpt.wav"
        _write_wav(path, _reference_excerpt())
        y, sr = load_analysis_audio(str(path))

        before = analyze_key(y, sr, correlation="pearson")
        after = analyze_key(y, sr)

        assert before.key == "C"
        assert after.key == "C"
        assert not before.is_low_confidence
        assert not after.is_low_confidence

        # Confidence saturates for both on genuinely tonal material...
        assert before.confidence == pytest.approx(1.0, abs=1.0e-9)
        assert after.confidence == pytest.approx(1.0, abs=1.0e-9)

        # ...while the underlying margins, which confidence is derived from,
        # are recorded because they are the quantity that actually changed.
        before_margin = before.winner_correlation - before.runner_up_correlation
        after_margin = after.winner_correlation - after.runner_up_correlation
        assert before_margin == pytest.approx(0.3765, abs=1.0e-3)
        assert after_margin == pytest.approx(0.0979, abs=1.0e-3)
        assert after_margin < before_margin

    def test_confidence_is_high_for_tonal_material_in_both_paths(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "reference_excerpt.wav"
        _write_wav(path, _reference_excerpt())
        y, sr = load_analysis_audio(str(path))
        for correlation in ("pearson", "cosine"):
            analysis = analyze_key(y, sr, correlation=correlation)
            assert analysis.confidence >= 0.4, correlation
            assert analysis.is_low_confidence is False

    def test_atonal_material_falls_back_under_both_paths(self, tmp_path: Path) -> None:
        """The real complement of the tonal excerpt: broadband noise written
        to and read back from the same real WAV path must yield the
        documented fallback, not a fabricated key.

        Re-measured under the F3 centring: the 16-bit WAV carries a tiny
        quantization DC residual, which the centring removes before the
        transform. Pearson margin 0.0459 / confidence 0.2293; cosine margin
        0.0015 / confidence 0.0188. Both fall back here, but see the margin
        comparison in the before/after test above for why only the cosine
        number can be relied on to stay put across noise seeds.
        """
        path = tmp_path / "reference_noise.wav"
        _write_wav(path, _white_noise(12345))
        y, sr = load_analysis_audio(str(path))
        measured = {"pearson": 0.2293, "cosine": 0.0188}
        for correlation, expected_confidence in measured.items():
            analysis = analyze_key(y, sr, correlation=correlation)
            assert analysis.key == UNKNOWN_KEY, correlation
            assert analysis.confidence == pytest.approx(expected_confidence, abs=1.0e-3)
            assert analysis.is_low_confidence is True, correlation


class TestGoldenVectorPositive:
    """Construct a key; the engine must detect exactly that key."""

    def test_pure_sine_plus_fifth_resolves_to_the_fundamental(
        self,
    ) -> None:
        """E4 + B4: only pitch classes E and B exist.

        A dyad has no defined mode, so the *root* is the absolute ground
        truth; the winning key's root must be E.
        """
        signal = _dyad_signal(64)
        key, strength = detect_key_with_strength(signal, SR)
        assert key.removesuffix("m") == "E"
        # Declared confidence band (measured 0.508 at HEAD): a dyad's
        # modality vote is undefined, so strength is a voicing artifact and
        # the band is deliberately wide.
        assert 0.10 <= strength <= 0.60

    def test_major_triads_all_12_detected_at_construction(self) -> None:
        """Every major triad is a positive vector: key == built key.

        Re-drives the pre-existing chromatic-roots contract through the
        *strength* API so its confidence semantics are pinned in-band too
        (measured 0.62–0.64 at HEAD, all 12 roots).
        """
        for note_name, midi_root in _MIDI_ROOTS.items():
            key, strength = detect_key_with_strength(_major_chord(midi_root), SR)
            expected = _MAJOR_EXPECTED[note_name]
            assert key == expected, (
                f"Major triad rooted at MIDI {midi_root} expected "
                f"'{expected}', got '{key}'"
            )
            assert 0.10 <= strength <= 0.90

    def test_minor_triads_all_12_detected_at_construction(self) -> None:
        """Every minor triad is a positive vector: key == built key, with a
        maximally decisive modality margin (measured 1.000 at HEAD)."""
        for note_name, midi_root in _MIDI_ROOTS.items():
            key, strength = detect_key_with_strength(_minor_chord(midi_root), SR)
            expected = _MINOR_EXPECTED[note_name]
            assert key == expected, (
                f"Minor triad rooted at MIDI {midi_root} expected "
                f"'{expected}', got '{key}'"
            )
            assert strength >= 0.10

    def test_progressions_resolve_to_the_tonic(self) -> None:
        """Multi-chord progressions whose diatonic pitch-class set uniquely
        determines the key.

        Both are hard assertions: an earlier draft guarded these with a
        conditional ``pytest.xfail`` on the theory that the G-major loop
        would mis-key as its relative minor, but that never actually
        happened (measured 'G', strength 0.530, twice and deterministically
        at HEAD), so the guard would have been dead code that silently
        absorbed any future regression on exactly the case most worth
        catching.
        """
        c_prog = np.concatenate([_major_chord(m) for m in (60, 65, 67, 60)])
        key, strength = detect_key_with_strength(c_prog, SR)
        assert key == "C", f"C I-IV-V-I detected as {key!r}"
        assert strength >= 0.10

        g_pop_loop = np.concatenate(
            [
                _major_chord(55),
                _major_chord(62),
                _minor_chord(64),
                _major_chord(60),
            ]
        )
        key, strength = detect_key_with_strength(g_pop_loop, SR)
        assert key == "G", f"G I-V-vi-IV detected as {key!r}"
        assert 0.10 <= strength <= 0.90


class TestGoldenVectorNegative:
    """The engine must be honest about ambiguous material."""

    def test_single_tone_reports_correct_root_at_floor_confidence(
        self,
    ) -> None:
        """One pure tone has no key; the engine may only name the relative
        pair whose root is the tone's pitch class, and only at a
        near-floor confidence.

        F2 re-measured this vector under the default cosine scoring: the
        named root is correct, but the modality flips to major (a single
        pitch is not evidence of a third either way) and confidence lands
        at 0.286-0.297 — above the 0.25 fallback threshold, so the tone is
        still named, but only just. Anything materially higher would be
        inventing a conviction a monophone cannot support, so the ceiling
        stays pinned here as the declared-tolerance boundary.

        Measured confidences: A 0.2967, D 0.2865, C 0.2861.
        """
        measured = {
            69: ("A", 0.2967),
            62: ("D", 0.2865),
            60: ("C", 0.2861),
        }
        for fundamental_midi, (expected_key, expected_confidence) in measured.items():
            key, confidence = detect_key_with_strength(
                _pure_tone(_midi_to_hz(fundamental_midi)), SR
            )
            assert key == expected_key, (
                f"Monophone at midi {fundamental_midi} should name the root "
                f"{expected_key}, got {key}"
            )
            assert abs(confidence - expected_confidence) < 1.0e-3, (
                f"Monophone at midi {fundamental_midi} confidence drifted: {confidence}"
            )
            assert confidence <= 0.35

    def test_white_noise_yields_the_documented_fallback(self) -> None:
        """White noise spans every pitch class with no tonal hierarchy.

        This is the F1 negative vector that item F2 explicitly hands to the
        low-confidence fallback. Under cosine scoring every seed's winning
        correlation lands within 0.0019 of the runner-up — a pseudo-random
        draw with no tonal meaning — so the engine must decline to name a
        key and report :data:`UNKNOWN_KEY` with a near-zero confidence
        instead of fabricating one.

        Measured at F2 across four seeds: keys all 'Unknown', confidences
        0.0089-0.0306, margins 0.0007-0.0024.
        """
        for seed in (12345, 2, 7, 99):
            generator = np.random.default_rng(seed)
            noise = generator.normal(0.0, 1.0, N_SAMPLES).astype(np.float64)
            key, confidence = detect_key_with_strength(noise, SR)
            assert key == UNKNOWN_KEY, (
                f"White noise seed {seed} must yield the documented fallback, got {key}"
            )
            assert 0.0 <= confidence <= 0.05

    def test_detection_is_deterministic_for_a_fixed_signal(self) -> None:
        """Seeded fixtures must yield identical results across calls — the
        reproducibility requirement of item F1's acceptance."""
        first = detect_key_with_strength(_dyad_signal(64), SR)
        second = detect_key_with_strength(_dyad_signal(64), SR)
        assert first == second

    def test_key_name_domain_is_the_internal_sharp_table(self) -> None:
        """The internal `_KEYS` table (what np.roll indexes) must be the
        domain the fixtures assert against, so a table change is loud."""
        internal_keys = [
            "C",
            "C#",
            "D",
            "D#",
            "E",
            "F",
            "F#",
            "G",
            "G#",
            "A",
            "A#",
            "B",
        ]
        for note_name, midi_root in _MIDI_ROOTS.items():
            assert internal_keys[midi_root % 12] == note_name


# ═════════════════════════════════════════════════════════════════════════════
# Low-confidence fallback and stated confidence (plan iteration 5, item F2 /
# audit #7)
# ═════════════════════════════════════════════════════════════════════════════


class TestStatedConfidence:
    """Clean, high-confidence material is stated as such.

    F2's requirement: a clean key must be reported as a *confident* key, so
    the fallback cannot quietly swallow ordinary music.
    """

    def test_clean_triad_is_reported_with_high_confidence(self) -> None:
        """Measured F2: C major 0.6731, A minor 0.8461 — comfortably clear of
        the 0.25 fallback threshold and of the atonal band (<= 0.031)."""
        for signal, expected_key, floor in (
            (_major_chord(60), "C", 0.65),
            (_minor_chord(57), "Am", 0.80),
        ):
            analysis = analyze_key(signal, SR)
            assert analysis.key == expected_key
            assert not analysis.is_low_confidence
            assert analysis.confidence >= floor
            assert analysis.confidence <= 1.0

    def test_progressions_are_reported_with_high_confidence(self) -> None:
        """Measured F2: C progression 0.6893, G pop loop 0.5460."""
        c_progression = np.concatenate(
            [_major_chord(m) for m in (60, 65, 67, 60)], axis=0
        )
        g_pop_loop = np.concatenate(
            [_major_chord(m) for m in (67, 72, 74, 67, 72, 74, 67, 72, 74, 67)],
            axis=0,
        )
        for signal, expected_key in ((c_progression, "C"), (g_pop_loop, "G")):
            analysis = analyze_key(signal, SR)
            assert analysis.key == expected_key
            assert not analysis.is_low_confidence
            assert analysis.confidence >= 0.5

    def test_confidence_is_derived_from_the_stated_margin(self) -> None:
        """The reported confidence must be reproducible from the two
        correlations the analysis exposes, so the number is auditable rather
        than an opaque scalar."""
        for signal in (_major_chord(60), _minor_chord(57), _major_chord(67)):
            analysis = analyze_key(signal, SR)
            margin = analysis.winner_correlation - analysis.runner_up_correlation
            assert analysis.winner_correlation > analysis.runner_up_correlation
            assert margin > 0.0
            assert 0.0 <= analysis.confidence <= 1.0
            assert analysis.confidence == pytest.approx(
                min(margin / 0.08, 1.0), abs=1.0e-12
            )


class TestLowConfidenceFallback:
    """Ambiguous material yields something honest.

    F2's requirement: the fallback is documented, deterministic, and returns
    a near-zero weight so a consumer cannot mistake it for a key.
    """

    def test_ambiguous_material_reports_the_fallback_not_a_key(self) -> None:
        for signal in (_white_noise(12345), _white_noise(2), np.ones(N_SAMPLES)):
            analysis = analyze_key(signal, SR)
            assert analysis.key == UNKNOWN_KEY
            assert analysis.is_low_confidence
            assert analysis.confidence < 0.25

    def test_fallback_confidence_is_near_zero_so_consumers_cannot_be_biased(
        self,
    ) -> None:
        """The mood analyser weights a major/minor valence offset by the
        strength returned here and treats any non-`m` key as major. A
        fallback must therefore carry near-zero weight, or an atonal file
        would acquire a spurious positive-valence contribution."""
        for seed in (12345, 2, 7, 99):
            key, strength = detect_key_with_strength(_white_noise(seed), SR)
            assert key == UNKNOWN_KEY
            assert 0.0 <= strength <= 0.05

    def test_the_fallback_is_deterministic(self) -> None:
        for seed in (12345, 2, 7, 99):
            first = detect_key_with_strength(_white_noise(seed), SR)
            second = detect_key_with_strength(_white_noise(seed), SR)
            assert first == second

    def test_mid_confidence_material_is_neither_upgraded_nor_dropped(self) -> None:
        """A monophone is the borderline case: it has a root but no key.

        It must not be silently promoted to a confident answer, and it must
        not be dropped to the fallback while a root is still identifiable.
        Measured F2: confidences 0.2861-0.2967, i.e. just above the
        threshold and far below the triad band (>= 0.65).
        """
        for midi, expected_key in ((60, "C"), (62, "D"), (69, "A")):
            analysis = analyze_key(_pure_tone(_midi_to_hz(midi)), SR)
            assert not analysis.is_low_confidence
            assert analysis.key == expected_key
            assert 0.25 <= analysis.confidence < 0.35

    def test_threshold_is_honoured_as_an_explicit_parameter(self) -> None:
        """The margin threshold is a documented parameter — and since F3 it
        is one of two gates, not the whole decision.

        The fallback fires only when the margin is below the threshold AND
        the material has no clear tonal centre (:data:`CLARITY_FLOOR`). A
        threshold of 0.0 disables the margin gate (every vote is
        'decisive'); on tonally clear material even a threshold of 1.0
        cannot force the fallback because the clarity gate names the key;
        and on tonally empty material the threshold still governs whether
        the (pseudo-random) vote is accepted.
        """
        signal = _major_chord(60)
        assert analyze_key(signal, SR, low_confidence_threshold=0.0).key == "C"
        # A triad is tonally decisive (clarity ~0.24, far above the floor),
        # so raising the margin threshold alone cannot force the fallback.
        tonal = analyze_key(signal, SR, low_confidence_threshold=1.0)
        assert tonal.key == "C"
        assert not tonal.is_low_confidence
        assert tonal.confidence == pytest.approx(
            analyze_key(signal, SR).confidence, abs=1.0e-12
        )
        # The threshold still governs material with no tonal centre: noise at
        # the default threshold falls back, and a threshold below its margin
        # accepts the vote.
        noise = _white_noise(12345)
        assert analyze_key(noise, SR).key == UNKNOWN_KEY
        named = analyze_key(noise, SR, low_confidence_threshold=0.001)
        assert named.key != UNKNOWN_KEY
        assert not named.is_low_confidence


class TestTonalityGate:
    """F3 (2026-10): real music with an ambiguous modal vote is still named.

    The report that triggered F3: seven of twelve tracks in a real album
    were 'Detected: Unknown' despite having a clear tonal centre, because
    their winner-to-runner-up margins were 0.001-0.015 and the old gate made
    the fallback fire on the margin alone. The noisy-triad vector below is
    the synthetic stand-in for that profile — the suite never ships
    commercial audio (F1 constraint) — so the defect is pinned to a
    behavior-lock test, not to the specific album.
    """

    def test_tonally_clear_material_with_an_ambiguous_vote_is_named(self) -> None:
        """A triad buried in noise: margin confidence ~0.08, so the old gate
        alone would have named it Unknown; tonal clarity ~0.08, well above
        the floor. The new rule names C major while leaving the reported
        confidence low, so consumers keep weighting it honestly."""
        analysis = analyze_key(_noisy_triad(60), SR)
        assert analysis.key == "C"
        assert not analysis.is_low_confidence
        assert analysis.clarity >= CLARITY_FLOOR
        assert analysis.confidence < 0.25

    def test_broadband_noise_has_no_tonal_centre(self) -> None:
        """The tonality gate measures what the margin cannot: pure broadband
        noise has no key standing out from the average, so its clarity sits
        far below the floor and every seed falls back."""
        for seed in (12345, 2, 7, 99):
            analysis = analyze_key(_white_noise(seed), SR)
            assert analysis.clarity < CLARITY_FLOOR, seed
            assert analysis.is_low_confidence, seed
            assert analysis.key == UNKNOWN_KEY, seed

    def test_dc_offset_is_centred_away_before_the_transform(self) -> None:
        """A pure DC offset previously scored a margin confidence of 0.180 —
        above six of the twelve real tracks in the F3 report. Centring makes
        it exactly zero-energy in the chroma domain, so the fallback is
        reported with a zero confidence and no tonal centre at all rather
        than a fabricated key."""
        analysis = analyze_key(np.ones(N_SAMPLES, dtype=np.float64), SR)
        assert analysis.key == UNKNOWN_KEY
        assert analysis.is_low_confidence
        assert analysis.confidence == 0.0
        assert analysis.clarity == 0.0


class TestScoringParameters:
    """The correlation method and weighting are explicit, documented knobs."""

    def test_pearson_remains_available_and_reproduces_the_legacy_answ(self) -> None:
        """`"pearson"` is the historical scoring path and still resolves every
        chromatic triad; it is retained for callers who depend on it, with
        the documented caveat that its margins do not separate atonal
        material as cleanly as cosine."""
        for midi_root in _MIDI_ROOTS.values():
            assert analyze_key(_major_chord(midi_root), SR, correlation="pearson").key
            assert analyze_key(_minor_chord(midi_root), SR, correlation="pearson").key

    def test_only_cosine_reliably_refuses_to_name_a_key_for_noise(self) -> None:
        """The measured justification for the default correlation.

        Across four seeds of pure white noise, Pearson's winner-to-runner-up
        margin is unstable enough that it names a key for two of them and
        calls it confident — 'Em' at 0.8995 and 'C#m' at 0.6565. Cosine
        declines all four, with confidences of 0.0089-0.0306.

        This is the specific defect F2 exists to fix, so it is asserted on
        the default rather than left as a comment.
        """
        pearson_named = [
            (seed, analyze_key(_white_noise(seed), SR, correlation="pearson"))
            for seed in (12345, 2, 7, 99)
        ]
        fabricated = [
            (seed, analysis.key, analysis.confidence)
            for seed, analysis in pearson_named
            if not analysis.is_low_confidence
        ]
        # The legacy path really does over-claim here; if a future change
        # stops it doing so, this assertion is what should be updated.
        assert len(fabricated) >= 1
        for seed in (12345, 2, 7, 99):
            analysis = analyze_key(_white_noise(seed), SR, correlation="cosine")
            assert analysis.key == UNKNOWN_KEY, seed
            assert analysis.confidence <= 0.05, seed

    def test_cosine_is_the_default(self) -> None:
        signal = _major_chord(60)
        default = analyze_key(signal, SR)
        explicit = analyze_key(signal, SR, correlation="cosine")
        assert default.key == explicit.key
        assert default.confidence == pytest.approx(explicit.confidence, abs=1.0e-12)

    def test_both_weightings_are_accepted_and_resolve_a_clean_triad(self) -> None:
        for weighting in ("uniform", "energy"):
            for signal, expected_key in (
                (_major_chord(60), "C"),
                (_minor_chord(57), "Am"),
            ):
                analysis = analyze_key(signal, SR, weighting=weighting)
                assert analysis.key == expected_key
                assert not analysis.is_low_confidence

    def test_energy_weighting_reweights_loud_material(self) -> None:
        """Energy weighting must actually change the profile it collapses, so
        the parameter is not decorative."""
        signal = _major_chord(60)
        uniform = analyze_key(signal, SR, weighting="uniform")
        energy = analyze_key(signal, SR, weighting="energy")
        assert energy.winner_correlation != uniform.winner_correlation
        assert energy.key == uniform.key


class TestPublicApiContract:
    """The pre-F2 entry points keep working, and share one analysis pass."""

    def test_detect_key_matches_analyze_key(self) -> None:
        for signal in (_major_chord(60), _minor_chord(57), _white_noise(12345)):
            assert detect_key(signal, SR) == analyze_key(signal, SR).key

    def test_detect_key_with_strength_reports_the_confidence(self) -> None:
        signal = _major_chord(60)
        key, strength = detect_key_with_strength(signal, SR)
        analysis = analyze_key(signal, SR)
        assert key == analysis.key
        assert strength == pytest.approx(analysis.confidence, abs=1.0e-12)

    def test_silence_still_raises_on_every_entry_point(self) -> None:
        silence: npt.NDArray[np.float64] = np.zeros(N_SAMPLES, dtype=np.float64)
        for call in (detect_key, detect_key_with_strength, analyze_key):
            with pytest.raises(AudioAnalysisError, match="zero-energy"):
                call(silence, SR)


_MIDI_ROOTS_BY_MIDI: dict[int, str] = {midi: name for name, midi in _MIDI_ROOTS.items()}


# ═════════════════════════════════════════════════════════════════════════════
# Licensed real-music key corpus (plan D147)
# ═════════════════════════════════════════════════════════════════════════════
# The synthetic fixtures above prove the estimator follows a key template; they
# cannot say how often it is right on real music, or whether its two thresholds
# are placed correctly.  The clips under tests/data/key_corpus are 20 s excerpts
# of Bach preludes and fugues performed by Kimiko Ishizaka (CC0).  ATTRIBUTION.md
# declares
# them and is the source of truth, so no clip can drift from its annotation.

KEY_CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests" / "data" / "key_corpus"
KEY_ATTRIBUTION_PATH = KEY_CORPUS_DIR / "ATTRIBUTION.md"

#: Corpus clips stay small enough to live in git, as the BPM corpus does.
_MAX_KEY_CLIP_BYTES = 200 * 1024

#: The recorded verdict vocabulary.  A "wrong (...)" outcome is a measured
#: defect, recorded rather than hidden: deleting the clip would delete the
#: evidence that the estimator picks a neighbour of the tonic.
_MATCHED = "matched"
_WRONG = (
    "wrong (dominant)",
    "wrong (mediant)",
    "wrong (relative major)",
    "wrong (relative minor)",
    "wrong (enharmonic twin)",
    "wrong (tritone)",
)

#: Clips named correctly when the corpus was recorded; locked so that any change
#: has to be deliberate and re-annotated.
_EXPECTED_MATCHES = 20

#: The annotated keys the estimator misses.  A fix updates the table and this set
#: together, which is the check that the fix actually moved the right rows.
_EXPECTED_WRONG_KEYS = {
    "D",
    "E",
    "Eb",
    "Em",
    "F",
    "F#",
    "Fm",
    "G",
    "G#m",
    "Ab",
    "B",
    "Bm",
}

#: Every clip is named by the shipped gate (the corpus measures which key wins,
#: not whether one is reported); the weakest clarity is 0.055 against 0.035.
_MIN_CORPUS_CLARITY = 0.055

#: The tonic-disjoint split declared in `ATTRIBUTION.md` (`## Split`): white-key
#: tonics train a variant, black-key tonics test it.  (correct, total) per half.
_BLACK_KEY_TONICS = {"C#", "D#", "F#", "G#", "A#"}
_FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
_EXPECTED_SPLIT = {"train": (12, 22), "test": (8, 12)}


@dataclass(frozen=True)
class _KeyClip:
    filename: str
    annotated_key: str
    measured_key: str
    clarity: float
    margin: float
    confidence: float
    outcome: str


def _key_rows() -> list[dict[str, str]]:
    return pipe_rows(
        KEY_ATTRIBUTION_PATH.read_text(encoding="utf-8"),
        "## Clips",
        name=KEY_ATTRIBUTION_PATH.name,
    )


def _key_clips() -> list[_KeyClip]:
    clips: list[_KeyClip] = []
    for row in _key_rows():
        clips.append(
            _KeyClip(
                filename=row["Clip"].strip("`"),
                annotated_key=row["Annotated key"],
                measured_key=row["Measured key"],
                clarity=float(row["Measured clarity"]),
                margin=float(row["Measured margin"]),
                confidence=float(row["Measured confidence"]),
                outcome=row["Outcome"],
            )
        )
    return clips


_KEY_ROWS = _key_rows()
_KEY_CLIPS = _key_clips()


class TestRealMusicKeyCorpus:
    """Measured accuracy on labelled real music, and why the gates stay put."""

    def test_the_committed_table_parses(self) -> None:
        assert len(_KEY_CLIPS) >= 10, f"only {len(_KEY_CLIPS)} rows parsed"
        outcomes = {clip.outcome for clip in _KEY_CLIPS}
        assert _MATCHED in outcomes, "no matched row - the accuracy claim is vacuous"
        assert outcomes - {_MATCHED}, "no recorded miss - the defect is hidden"
        assert outcomes <= {_MATCHED, *_WRONG}, (
            f"unknown outcome vocabulary: {outcomes}"
        )

    def test_the_corpus_is_complete_and_attributed(self) -> None:
        files = sorted(path.name for path in KEY_CORPUS_DIR.glob("*.ogg"))
        assert files == sorted(
            [clip.filename for clip in _KEY_CLIPS]
            + [clip.filename for clip in _DENSE_CLIPS]
        ), (
            "the committed clips and the table diverged - a clip is missing its "
            "row, or a row is missing its clip"
        )
        for row in _KEY_ROWS:
            path = KEY_CORPUS_DIR / row["Clip"].strip("`")
            assert path.is_file()
            assert path.stat().st_size <= _MAX_KEY_CLIP_BYTES, (
                f"{path.name} is {path.stat().st_size} bytes; corpus clips must "
                f"stay under {_MAX_KEY_CLIP_BYTES}"
            )
            assert row["Licence"] == "CC0 1.0", (
                f"{path.name}: licence {row['Licence']!r} is not the verified CC0 "
                "dedication this corpus requires"
            )
            assert row["Source"].startswith(
                "<https://commons.wikimedia.org/wiki/File:"
            ), f"{path.name}: {row['Source']!r} is not a Commons file page"
            assert row["Author"] == "Kimiko Ishizaka"
            duration = librosa.get_duration(path=str(path))
            assert 19.0 <= duration <= 21.0, f"{path.name}: duration {duration}"

    def test_every_clip_measures_what_the_table_records(self) -> None:
        for clip in _KEY_CLIPS:
            signal, sr = load_analysis_audio(str(KEY_CORPUS_DIR / clip.filename))
            analysis = analyze_key(signal, sr)
            assert analysis.key == clip.measured_key, (
                f"{clip.filename}: the table records {clip.measured_key}, the "
                f"engine now says {analysis.key} - re-annotate the row"
            )
            assert analysis.clarity == pytest.approx(clip.clarity, abs=0.02)
            assert (
                analysis.winner_correlation - analysis.runner_up_correlation
            ) == pytest.approx(clip.margin, abs=0.01)
            assert analysis.confidence == pytest.approx(clip.confidence, abs=0.05)

    def test_the_measured_accuracy_is_locked(self) -> None:
        matched = [clip for clip in _KEY_CLIPS if clip.outcome == _MATCHED]
        wrong = {clip.annotated_key for clip in _KEY_CLIPS if clip.outcome != _MATCHED}
        assert len(matched) == _EXPECTED_MATCHES
        assert wrong == _EXPECTED_WRONG_KEYS, (
            f"the recorded misses are {sorted(wrong)}, not "
            f"{sorted(_EXPECTED_WRONG_KEYS)}: the known failures are the dominant, "
            "the mediant and the relative minor; a fix updates the table and this "
            "set together"
        )
        for clip in _KEY_CLIPS:
            if clip.outcome != _MATCHED:
                assert clip.measured_key != clip.annotated_key

    def test_the_thresholds_cannot_move_the_accuracy(self) -> None:
        """Re-running the gate over these rows: same answer at every setting.

        This is why D147 re-derived neither threshold.  The winner is decided by
        the winning correlation, so a gate threshold changes which clips are
        *named*, never which key wins.
        """

        def exact_named(confidence_threshold: float, clarity_floor: float) -> int:
            named = [
                clip
                for clip in _KEY_CLIPS
                if clip.confidence >= confidence_threshold
                or clip.clarity >= clarity_floor
            ]
            return sum(1 for clip in named if clip.measured_key == clip.annotated_key)

        base = exact_named(DEFAULT_LOW_CONFIDENCE_THRESHOLD, CLARITY_FLOOR)
        assert base == _EXPECTED_MATCHES
        for floor in (0.040, 0.047, 0.055):
            assert exact_named(DEFAULT_LOW_CONFIDENCE_THRESHOLD, floor) == base, (
                f"a {floor} clarity floor changes the correct count; if a threshold "
                "really can repair a miss, D147 must be re-derived from it"
            )
        for threshold in (0.05, 0.10, 0.40, 0.60):
            assert exact_named(threshold, CLARITY_FLOOR) == base, (
                f"a {threshold} margin threshold changes the correct count"
            )

    def test_a_stricter_floor_refuses_music_without_fixing_it(self) -> None:
        """The 0.070 counterfactual: fewer clips named, none of them repaired."""
        named = [
            clip
            for clip in _KEY_CLIPS
            if clip.confidence >= DEFAULT_LOW_CONFIDENCE_THRESHOLD
            or clip.clarity >= 0.070
        ]
        correct = sum(1 for clip in named if clip.measured_key == clip.annotated_key)
        assert len(named) == 25, f"0.070 names {len(named)} clips, not 25"
        assert correct == 17, f"0.070 names {len(named)} clips and corrects {correct}"
        # The invariant behind the numbers: a floor can only remove named clips,
        # so it can never raise the number of correct answers.
        assert correct <= _EXPECTED_MATCHES, (
            f"a 0.070 floor corrects {correct} clips against {_EXPECTED_MATCHES} "
            "at the shipped floor; a gate threshold cannot repair a miss"
        )

    def test_every_clip_is_named(self) -> None:
        """The corpus measures the winner, not whether a key is reported.

        Every clip sits above the clarity floor, so a change that starts refusing
        one has changed coverage rather than accuracy, and this lock says so
        before a threshold absorbs it.
        """
        refused = [
            clip.filename for clip in _KEY_CLIPS if clip.measured_key == UNKNOWN_KEY
        ]
        assert not refused, f"the shipped gate refuses corpus clips: {refused}"
        weakest = min(_KEY_CLIPS, key=lambda clip: clip.clarity)
        assert weakest.clarity >= _MIN_CORPUS_CLARITY, (
            f"{weakest.filename} measures clarity {weakest.clarity:.3f}, below the "
            f"recorded weakest {_MIN_CORPUS_CLARITY}; re-measure the corpus before "
            "moving a floor"
        )

    def test_the_split_is_tonic_disjoint_and_scored(self) -> None:
        """The declared split, and the shipped engine's score on each half.

        A variant fitted on the white-key half is reported on the black-key half,
        so the halves must not share a tonic: a corpus split by pitch class would
        let a variant be credited on the keys it learned.
        """

        def tonic(clip: _KeyClip) -> str:
            name = (
                clip.annotated_key[:-1]
                if clip.annotated_key.endswith("m")
                else clip.annotated_key
            )
            return _FLAT_TO_SHARP.get(name, name)

        train = [clip for clip in _KEY_CLIPS if tonic(clip) not in _BLACK_KEY_TONICS]
        test = [clip for clip in _KEY_CLIPS if tonic(clip) in _BLACK_KEY_TONICS]
        assert len(train) + len(test) == len(_KEY_CLIPS), (
            "the split does not partition the corpus"
        )
        assert {tonic(clip) for clip in train}.isdisjoint(
            {tonic(clip) for clip in test}
        ), "a tonic is in both halves - the split is not tonic-disjoint"
        for half, clips in (("train", train), ("test", test)):
            expected_correct, expected_total = _EXPECTED_SPLIT[half]
            assert len(clips) == expected_total, (
                f"the {half} half holds {len(clips)} clips, not {expected_total}"
            )
            named = sum(1 for clip in clips if clip.measured_key == clip.annotated_key)
            assert named == expected_correct, (
                f"the {half} half is named correctly {named} times, not "
                f"{expected_correct}; re-record the split in ATTRIBUTION.md and here"
            )

    def test_the_thresholds_are_pinned(self) -> None:
        assert CLARITY_FLOOR == 0.035, (
            f"CLARITY_FLOOR is {CLARITY_FLOOR}, not the calibrated 0.035; the key "
            "corpus gives no evidence for another value (accuracy is unchanged at "
            "0.040-0.055), so a move needs its own re-derivation (D147)"
        )
        assert DEFAULT_LOW_CONFIDENCE_THRESHOLD == 0.25, (
            f"the margin threshold is {DEFAULT_LOW_CONFIDENCE_THRESHOLD}, not the "
            "calibrated 0.25; the corpus shows it is inert on real material "
            "(0.05-0.60 all give the same accuracy), not that another value is better"
        )


# ── Dense electronic corpus (D152) ───────────────────────────────────────────
# The Bach table above is solo keyboard and every one of its clips is named on the
# first pass, so it cannot say how the percussion-removed second pass behaves on
# the dense, drum-led masters it exists for.  These four sections of two CC0
# electronic works carry a key the *source* states, which is what lets that pass be
# scored for accuracy rather than only for yield.
#
# Changed in 2.7.0: added the dense electronic table (D152).

#: The licence and author the dense rows must carry, both read from the FMA page.
_DENSE_SOURCE_PREFIX = "<https://freemusicarchive.org/music/beat-mekanik/"
_DENSE_AUTHOR = "Johnathon M. Horner (Beat Mekanik)"

#: Sections named correctly: both Electron sections.  The two misses are the same
#: relative-minor confusion the Bach table records for F major.
_EXPECTED_DENSE_MATCHES = 2
_EXPECTED_DENSE_WRONG = {"F": "Dm"}


@dataclass(frozen=True)
class _DenseClip:
    filename: str
    annotated_key: str
    measured_key: str
    clarity: float
    margin: float
    confidence: float
    harmonic_key: str
    harmonic_clarity: float
    analysis_path: str
    outcome: str


def _dense_rows() -> list[dict[str, str]]:
    return pipe_rows(
        KEY_ATTRIBUTION_PATH.read_text(encoding="utf-8"),
        "## Dense clips",
        name=KEY_ATTRIBUTION_PATH.name,
    )


def _dense_clips() -> list[_DenseClip]:
    return [
        _DenseClip(
            filename=row["Clip"].strip("`"),
            annotated_key=row["Annotated key"],
            measured_key=row["Measured key"],
            clarity=float(row["Measured clarity"]),
            margin=float(row["Measured margin"]),
            confidence=float(row["Measured confidence"]),
            harmonic_key=row["Harmonic key"],
            harmonic_clarity=float(row["Harmonic clarity"]),
            analysis_path=row["Pass"],
            outcome=row["Outcome"],
        )
        for row in _dense_rows()
    ]


_DENSE_ROWS = _dense_rows()
_DENSE_CLIPS = _dense_clips()


class TestDenseElectronicCorpus:
    """Measured accuracy on dense masters whose key the source states (D152).

    What these rows measure is that the retry is not what a dense master needs:
    all four sections are named on the first pass (clarity 0.060-0.166, against a
    0.035 floor), so the second pass never runs on them in production, and where
    the answer is wrong it stays wrong after percussion removal - the one miss is
    F major read as its relative minor ``Dm`` on both the first and the harmonic
    pass.  The defect the retry was built for is drum masking; this defect is in
    the pitch-class content, which is why no percussion treatment repairs it.

    The ``Harmonic ...`` columns are `_harmonic_pass` measured directly, so the
    table records what that pass *would* say without claiming the engine said it.
    """

    def test_the_dense_table_parses(self) -> None:
        assert len(_DENSE_CLIPS) == 4, f"only {len(_DENSE_CLIPS)} dense rows parsed"
        assert len(_DENSE_ROWS) == len(_DENSE_CLIPS)
        outcomes = {clip.outcome for clip in _DENSE_CLIPS}
        assert _MATCHED in outcomes, "no matched row - the accuracy claim is vacuous"
        assert outcomes - {_MATCHED}, "no recorded miss - the defect is hidden"
        assert outcomes <= {_MATCHED, *_WRONG}, (
            f"unknown outcome vocabulary: {outcomes}"
        )

    def test_the_dense_clips_are_attributed(self) -> None:
        for row in _DENSE_ROWS:
            path = KEY_CORPUS_DIR / row["Clip"].strip("`")
            assert path.is_file(), f"{path.name} is missing its clip"
            assert path.stat().st_size <= _MAX_KEY_CLIP_BYTES, (
                f"{path.name} is {path.stat().st_size} bytes; corpus clips must "
                f"stay under {_MAX_KEY_CLIP_BYTES}"
            )
            assert row["Licence"] == "CC0 1.0", (
                f"{path.name}: licence {row['Licence']!r} is not the verified CC0 "
                "dedication this corpus requires"
            )
            assert row["Source"].startswith(_DENSE_SOURCE_PREFIX), (
                f"{path.name}: {row['Source']!r} is not the Free Music Archive track "
                "page whose cue info states the key"
            )
            assert row["Author"] == _DENSE_AUTHOR, (
                f"{path.name}: author {row['Author']!r} is not the artist who "
                "released these works CC0"
            )
            assert row["Offset"].rstrip(" s") in {"0.00", "90.00"}, (
                f"{path.name}: offset {row['Offset']!r} is not a measured section"
            )
            duration = librosa.get_duration(path=str(path))
            assert 19.0 <= duration <= 21.0, f"{path.name}: duration {duration}"

    def test_every_dense_clip_measures_what_the_table_records(self) -> None:
        for clip in _DENSE_CLIPS:
            signal, sr = load_analysis_audio(str(KEY_CORPUS_DIR / clip.filename))
            analysis = analyze_key(signal, sr)
            assert analysis.key == clip.measured_key, (
                f"{clip.filename}: the table records {clip.measured_key}, the "
                f"engine now says {analysis.key} - re-annotate the row"
            )
            assert analysis.analysis_path == clip.analysis_path == "chroma", (
                f"{clip.filename}: the {analysis.analysis_path} pass answered where "
                "the table records the first pass; if a dense master now reaches the "
                "retry, re-measure every dense row"
            )
            assert analysis.clarity == pytest.approx(clip.clarity, abs=0.02)
            margin = analysis.winner_correlation - analysis.runner_up_correlation
            assert margin == pytest.approx(clip.margin, abs=0.01)
            assert analysis.confidence == pytest.approx(clip.confidence, abs=0.05)

    def test_the_recorded_harmonic_pass_matches_the_table(self) -> None:
        for clip in _DENSE_CLIPS:
            signal, sr = load_analysis_audio(str(KEY_CORPUS_DIR / clip.filename))
            harmonic = _harmonic_pass(
                signal.astype(np.float64), sr, DEFAULT_CORRELATION, DEFAULT_WEIGHTING
            )
            assert harmonic is not None, f"{clip.filename}: nothing left to score"
            h_key, _h_winner, _h_runner, _h_conf, h_clarity = harmonic
            assert h_key == clip.harmonic_key, (
                f"{clip.filename}: the harmonic pass now says {h_key}, the table "
                f"records {clip.harmonic_key}"
            )
            assert h_clarity == pytest.approx(clip.harmonic_clarity, abs=0.02)

    def test_dense_accuracy_and_the_unrepaired_miss_are_locked(self) -> None:
        matched = [clip for clip in _DENSE_CLIPS if clip.outcome == _MATCHED]
        wrong = {
            clip.annotated_key: clip.measured_key
            for clip in _DENSE_CLIPS
            if clip.outcome != _MATCHED
        }
        assert len(matched) == _EXPECTED_DENSE_MATCHES, (
            f"{len(matched)} dense sections are named correctly, not "
            f"{_EXPECTED_DENSE_MATCHES}; a change to this number is a change to the "
            "measured accuracy on dense electronic material"
        )
        assert wrong == _EXPECTED_DENSE_WRONG, (
            f"the recorded dense misses are {wrong}, not {_EXPECTED_DENSE_WRONG}"
        )
        for clip in _DENSE_CLIPS:
            assert clip.harmonic_key == clip.measured_key, (
                f"{clip.filename}: the harmonic pass says {clip.harmonic_key} where "
                f"the first pass says {clip.measured_key}; percussion removal is "
                "supposed not to change a verdict, so re-measure the table"
            )


# ── Atonal noise boundary ─────────────────────────────────────────────────────


_BROWN_SEEDS: range = range(10)
_BAND_LIMITED_BANDS: tuple[tuple[float, float], ...] = (
    (60.0, 6000.0),
    (300.0, 3000.0),
    (2000.0, 6000.0),
)

#: Recorded ceilings (20 s, engine 2.7.0): the worst of ten brown seeds and the
#: worst of the three bands.  Pinned so a statistic change that quietly moves
#: the noise floor shows up before a threshold has to absorb it.
_MEASURED_BROWN_CEILING: float = 0.0265
_MEASURED_BAND_CEILING: float = 0.0229


class TestAtonalNoiseFloor:
    """Coloured noise must not fit a key template (D149).

    ``CLARITY_FLOOR`` is the gate that decides on material with no tonal centre:
    the margin threshold is inert here (these signals measure 0.000-0.13
    confidence), so if a noise profile ever starts spanning several pitch
    classes, the floor is the only thing between it and a written key tag.  A
    key detector that tags a rumble or a hiss is worse than one that declines -
    the tag reads as a musical fact (F2).

    Two measured limits are recorded rather than locked, because no threshold can
    address either without refusing real music.  At a 3 s window, brown noise's
    clarity is seed-dependent enough that one seed in ten crosses the floor; at
    its 0.038 ceiling the floor would have to rise to 0.045 to refuse it, which
    is above the median clarity D146 measured across a real pop library (0.047).
    And a 400 Hz-wide band at 800-1200 Hz is *named* (Am/Bm at 0.034-0.040,
    both window lengths): a band that narrow is a pitched hiss, which ``chroma``
    reads as a chord, and the gates have no spectral-flatness test to tell the
    two apart.  Refusing it would need a new feature, not a moved constant.
    """

    def test_brown_noise_is_never_named(self) -> None:
        worst_seed: int = -1
        worst_clarity: float = 0.0
        for seed in _BROWN_SEEDS:
            analysis = analyze_key(_brown_noise(seed), SR)
            if analysis.clarity > worst_clarity:
                worst_seed, worst_clarity = seed, analysis.clarity
            assert analysis.key == UNKNOWN_KEY, (
                f"brown-noise seed {seed} was named {analysis.key!r} at clarity "
                f"{analysis.clarity:.4f}; low-frequency rumble is not in a key"
            )
            assert analysis.clarity < CLARITY_FLOOR, (
                f"brown-noise seed {seed} measures clarity {analysis.clarity:.4f} "
                f"against the {CLARITY_FLOOR} floor - the noise profile now fits a "
                "key template closely enough to pass the tonality gate"
            )
        assert worst_clarity == pytest.approx(_MEASURED_BROWN_CEILING, abs=0.005), (
            f"the worst brown-noise seed ({worst_seed}) now measures "
            f"{worst_clarity:.4f} against a recorded {_MEASURED_BROWN_CEILING}; "
            "re-measure the noise band before moving CLARITY_FLOOR"
        )

    def test_band_limited_noise_is_never_named(self) -> None:
        worst_clarity: float = 0.0
        for low_hz, high_hz in _BAND_LIMITED_BANDS:
            for seed in range(3):
                analysis = analyze_key(_band_limited_noise(seed, low_hz, high_hz), SR)
                worst_clarity = max(worst_clarity, analysis.clarity)
                assert analysis.key == UNKNOWN_KEY, (
                    f"band-limited noise {low_hz}-{high_hz} Hz, seed {seed}, was "
                    f"named {analysis.key!r} at clarity {analysis.clarity:.4f}"
                )
                assert analysis.clarity < CLARITY_FLOOR, (
                    f"band-limited noise {low_hz}-{high_hz} Hz, seed {seed}, "
                    f"measures clarity {analysis.clarity:.4f} against the "
                    f"{CLARITY_FLOOR} floor"
                )
        assert worst_clarity == pytest.approx(_MEASURED_BAND_CEILING, abs=0.005), (
            f"the worst band-limited fixture now measures {worst_clarity:.4f} "
            f"against a recorded {_MEASURED_BAND_CEILING}; re-measure the noise "
            "band before moving CLARITY_FLOOR"
        )

    def test_the_fixtures_are_audible_noise(self) -> None:
        """A silent fixture would pass every floor assertion vacuously."""
        for signal in (
            _brown_noise(0),
            _band_limited_noise(0, 300.0, 3000.0),
        ):
            rms: float = float(np.sqrt(np.mean(np.square(signal))))
            assert 0.01 < rms < 0.5, f"fixture RMS {rms:.4f} is not audible noise"
            # The detrended brown walk has two exactly-zero endpoints; a silent
            # fixture would be almost entirely zero rather than two samples.
            non_zero = float(np.count_nonzero(signal)) / signal.size
            assert non_zero > 0.99, f"only {non_zero:.1%} of the fixture is non-zero"


# ── Harmonic second pass (D151) ──────────────────────────────────────────────

_HARMONIC_FIXTURE_SECONDS: float = 5.0

#: The fixture's measured full-spectrum clarity, pinned so the class cannot pass
#: vacuously: if the first pass ever stops refusing it, the retry is no longer
#: being exercised and this number is the tripwire.
_MEASURED_FIXTURE_CLARITY: float = 0.0285


def _chord_under_noise(seed: int = 11) -> npt.NDArray[np.float64]:
    """An A-major chord buried under noise the full-spectrum pass cannot use.

    Measured: the first pass scores clarity 0.0285 (below ``CLARITY_FLOOR``) and
    refuses, while the percussion-suppressed pass finds A at 0.0881 (above
    ``HARMONIC_CLARITY_FLOOR``).  It is the synthetic stand-in for the dense
    mixes the retry exists for - pitch content present but outweighed by
    broadband energy.
    """
    n = int(SR * _HARMONIC_FIXTURE_SECONDS)
    t = np.arange(n) / SR
    chord = (
        sum(np.sin(2.0 * np.pi * 220.0 * ratio * t) for ratio in (1.0, 1.26, 1.5)) / 3
    )
    noisy = chord + 2.5 * np.random.default_rng(seed).standard_normal(n)
    return (noisy / np.max(np.abs(noisy))).astype(np.float64)


def _coloured_noise(
    color: str, seed: int, seconds: float = 20.0
) -> npt.NDArray[np.float64]:
    """Seeded white, pink (1/f) or brown (detrended walk) noise."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    signal = rng.standard_normal(n)
    if color == "brown":
        signal = np.cumsum(signal)
        signal -= np.linspace(signal[0], signal[-1], n)
    elif color == "pink":
        freqs: npt.NDArray[np.float64] = np.fft.rfftfreq(n, 1 / SR)
        freqs[0] = 1.0
        signal = np.fft.irfft(np.fft.rfft(signal) / np.sqrt(freqs), n)
    return (signal / np.max(np.abs(signal)) * 0.5).astype(np.float64)


def _first_pass_clarity(signal: npt.NDArray[np.float64]) -> float:
    """The clarity the full-spectrum pass alone would report for *signal*."""
    chroma = librosa.feature.chroma_cqt(y=signal, sr=SR).astype(np.float64)
    _, _, _, _, clarity = _score_profile(
        _pitch_class_profile(chroma, "uniform"), "cosine"
    )
    return clarity


class TestHarmonicSecondPass:
    """A refused file is measured once more with percussion removed (D151).

    The first pass is untouched: a file it names keeps that key, so this path
    can only add keys to files that would otherwise be reported DETECTED.  Its
    own floor sits above the measured noise ceiling, because removing percussion
    raises the clarity of noise as well as of music.
    """

    def test_the_fixture_really_is_refused_by_the_first_pass(self) -> None:
        clarity = _first_pass_clarity(_chord_under_noise())
        assert clarity == pytest.approx(_MEASURED_FIXTURE_CLARITY, abs=0.005)
        assert clarity < CLARITY_FLOOR, (
            "the fixture now clears the first-pass floor, so it no longer "
            "exercises the second pass"
        )

    def test_a_chord_under_noise_is_named_by_the_second_pass(self) -> None:
        analysis = analyze_key(_chord_under_noise(), SR)
        assert analysis.analysis_path == "harmonic"
        assert analysis.key == "A"
        assert not analysis.is_low_confidence
        assert analysis.clarity >= HARMONIC_CLARITY_FLOOR

    def test_a_named_file_is_never_re_resolved(self) -> None:
        """The retry runs only behind a refusal, so the first pass is authoritative."""
        analysis = analyze_key(_major_chord(60), SR)
        assert analysis.analysis_path == "chroma"
        assert analysis.key == "C"

    @pytest.mark.parametrize("color", ["white", "pink", "brown"])
    def test_coloured_noise_survives_both_passes_as_unknown(self, color: str) -> None:
        for seed in range(2):
            analysis = analyze_key(_coloured_noise(color, seed), SR)
            assert analysis.key == UNKNOWN_KEY, (
                f"{color} noise seed {seed} was named {analysis.key!r} "
                f"({analysis.analysis_path} pass, clarity {analysis.clarity:.4f})"
            )
            assert analysis.analysis_path == "chroma"
            assert analysis.clarity < CLARITY_FLOOR

    def test_band_limited_noise_clears_neither_floor(self) -> None:
        analysis = analyze_key(_band_limited_noise(0, 2000.0, 6000.0), SR)
        assert analysis.key == UNKNOWN_KEY
        assert analysis.analysis_path == "chroma"
        assert analysis.clarity < CLARITY_FLOOR

    def test_the_harmonic_floor_is_pinned(self) -> None:
        assert HARMONIC_CLARITY_FLOOR == 0.065, (
            f"HARMONIC_CLARITY_FLOOR is {HARMONIC_CLARITY_FLOOR}, not the "
            "calibrated 0.065: the measured noise ceiling under percussion "
            "removal is 0.0553 (2-6 kHz band, ten seeds) and a chord-under-noise "
            "fixture measures 0.0745, so 0.065 is the midpoint. A move needs its "
            "own calibration (D151)"
        )
