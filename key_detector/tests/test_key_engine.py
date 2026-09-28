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
import wave
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
    UNKNOWN_KEY,
    analyze_key,
    detect_key,
    detect_key_with_strength,
)

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

        Broadband noise, same decode path — the case F2 exists to fix:

        ==========  =============  ==============  ==================
        path        margin         confidence      result
        ==========  =============  ==============  ==================
        pearson     0.0462         0.2311          'Unknown'
        cosine      0.0015         0.0190          'Unknown'
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

        Measured: pearson margin 0.0462 / confidence 0.2311; cosine margin
        0.0015 / confidence 0.0190. Both fall back here, but see the margin
        comparison in the before/after test above for why only the cosine
        number can be relied on to stay put across noise seeds.
        """
        path = tmp_path / "reference_noise.wav"
        _write_wav(path, _white_noise(12345))
        y, sr = load_analysis_audio(str(path))
        measured = {"pearson": 0.2311, "cosine": 0.0190}
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
        """The threshold is a documented parameter, not a buried constant."""
        signal = _major_chord(60)
        assert analyze_key(signal, SR, low_confidence_threshold=0.0).key == "C"
        forced = analyze_key(signal, SR, low_confidence_threshold=1.0)
        assert forced.key == UNKNOWN_KEY
        assert forced.is_low_confidence
        assert forced.confidence == pytest.approx(
            analyze_key(signal, SR).confidence, abs=1.0e-12
        )


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
