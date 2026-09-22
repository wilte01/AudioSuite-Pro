"""
signal_mood_engine.py
Deterministic mood analysis from the audio signal itself, based on the
Russell valence–arousal circumplex model of affect.

Pure module — no tkinter imports, no file I/O.  Accepts a pre-loaded audio
signal (numpy array + sample rate) and returns a MoodAnalysis dataclass.

Theory (Russell, 1980): emotions are points on two orthogonal dimensions —
valence (pleasant ↔ unpleasant) and arousal (activated ↔ calm).  Music
signal correlates with these dimensions fairly well:

  * Arousal  ← tempo/BPM, spectral flux (energy change), RMS energy,
                zero-crossing rate.
  * Valence  ← modality (major/minor), spectral brightness, low-band energy.

Features are normalised against perceptually anchored scales and blended
onto the circumplex deterministically.  The resulting valence/arousal point
selects a mood word from a 4×4 quadrant taxonomy via nearest-neighbour
lookup, trimmed to the top-3 ranked candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import AudioAnalysisError

logger = logging.getLogger(__name__)

# ── Perceptual anchors for feature normalisation ─────────────────────────────
# Each entry maps a feature value to its contribution to either valence or
# arousal in [-1, 1].  Scales are chosen to match typical music values.

# Arousal contributors: value → "fraction of full activation".
_AROUSAL_BPM_LO = 70.0
_AROUSAL_BPM_HI = 170.0

_AROUSAL_FLUX_LO = 0.01
_AROUSAL_FLUX_HI = 0.10

_AROUSAL_ZCR_LO = 0.02
_AROUSAL_ZCR_HI = 0.15

_AROUSAL_RMS_LO = 0.05
_AROUSAL_RMS_HI = 0.30

# Valence contributors.
# Spectral centroid (Hz) → brightness/pleasantness.
_VALENCE_CENTROID_LO = 800.0
_VALENCE_CENTROID_HI = 5000.0

# Fraction of spectral energy in the sub-250 Hz band → melancholic colour.
_VALENCE_LOWBAND_LO = 0.15
_VALENCE_LOWBAND_HI = 0.55

# Modality contribution magnitudes (sign chosen by major/minor).
_VALENCE_MAJOR_WEIGHT = 0.85
_VALENCE_MINOR_WEIGHT = -0.85


@dataclass(frozen=True)
class MoodAnalysis:
    """Result of analysing one audio signal's mood.

    Attributes:
        valence:    Score in [-1, 1] on the pleasant–unpleasant axis.
        arousal:    Score in [-1, 1] on the activated–calm axis.
        mood_words: Top-3 ranked descriptive mood words (most confident first).
        confidence: Overall confidence in [0, 1] (1 = most confident).
        energy:     Discretised arousal band, 1 (calm) .. 6 (very energetic).
    """

    valence: float
    arousal: float
    mood_words: tuple[str, str, str]
    confidence: float
    energy: int

    def to_tag_string(self) -> str:
        """Return the semicolon-joined mood string used in the TMOO tag.

        Returns:
            e.g. ``'Energetic;Bright;Confident'``.
        """
        return ";".join(self.mood_words)


# ── Circumplex taxonomy ───────────────────────────────────────────────────────
# 4 arousal bands × 4 valence bands → primary mood word.  High arousal +
# high valence = energetic/positive; low arousal + low valence = calm/dark.
_MOOD_MATRIX: tuple[tuple[str, ...], ...] = (
    ("Dreary", "Melancholic", "Reflective", "Serene"),
    ("Grim", "Somber", "Peaceful", "Tender"),
    ("Restless", "Pensive", "Hopeful", "Warm"),
    ("Tense", "Driving", "Playful", "Energetic"),
)

# Extended vocabulary used to fill the 2nd/3rd ranks from the winning cell's
# neighbours. Each 4-tuple is ranked by closeness in the valence–arousal
# plane: (winner, horizontal-neighbour, vertical-sibling, diagonal).
# Horizontal neighbours strictly respect valence polarity (staying within the
# negative hemisphere for cols 0-1 and positive hemisphere for cols 2-3).
_MOOD_RANKING: dict[str, tuple[str, str, str, str]] = {
    # Negative valence hemisphere (cols 0 & 1)
    "Dreary": ("Dreary", "Melancholic", "Grim", "Somber"),
    "Melancholic": ("Melancholic", "Dreary", "Somber", "Grim"),
    "Grim": ("Grim", "Somber", "Dreary", "Melancholic"),
    "Somber": ("Somber", "Grim", "Melancholic", "Dreary"),
    "Restless": ("Restless", "Pensive", "Tense", "Driving"),
    "Pensive": ("Pensive", "Restless", "Driving", "Somber"),
    "Tense": ("Tense", "Driving", "Restless", "Pensive"),
    "Driving": ("Driving", "Tense", "Pensive", "Restless"),
    # Positive valence hemisphere (cols 2 & 3)
    "Reflective": ("Reflective", "Serene", "Peaceful", "Tender"),
    "Serene": ("Serene", "Reflective", "Tender", "Peaceful"),
    "Peaceful": ("Peaceful", "Tender", "Reflective", "Serene"),
    "Tender": ("Tender", "Peaceful", "Serene", "Reflective"),
    "Hopeful": ("Hopeful", "Warm", "Playful", "Peaceful"),
    "Warm": ("Warm", "Hopeful", "Energetic", "Tender"),
    "Playful": ("Playful", "Energetic", "Hopeful", "Warm"),
    "Energetic": ("Energetic", "Playful", "Warm", "Hopeful"),
}

_QUADRANT_ROW = 4  # arousal bands
_QUADRANT_COL = 4  # valence bands

_EXPECTED_WORD_COUNT = 3


# ── Feature → axis mapping helpers ────────────────────────────────────────────


def _normalise(value: float, lo: float, hi: float) -> float:
    """Map *value* from [lo, hi] to [-1, 1], clipped at the bounds.

    Args:
        value: Raw feature value.
        lo:    Value that maps to -1.
        hi:    Value that maps to +1.

    Returns:
        Normalised score in [-1, 1].
    """
    if hi <= lo:
        return 0.0
    return float(np.clip((value - lo) / (hi - lo) * 2.0 - 1.0, -1.0, 1.0))


def _tempo_to_arousal(bpm: float) -> float:
    """Map a detected BPM onto the arousal axis.

    Args:
        bpm: Beats-per-minute value (non-negative).

    Returns:
        Arousal contribution in [-1, 1].
    """
    return _normalise(bpm, _AROUSAL_BPM_LO, _AROUSAL_BPM_HI)


def _flux_to_arousal(flux: float) -> float:
    """Map mean spectral flux onto the arousal axis.

    Args:
        flux: Mean per-frame spectral flux.

    Returns:
        Arousal contribution in [-1, 1].
    """
    return _normalise(flux, _AROUSAL_FLUX_LO, _AROUSAL_FLUX_HI)


def _zcr_to_arousal(zcr: float) -> float:
    """Map mean zero-crossing rate onto the arousal axis.

    Args:
        zcr: Mean zero-crossing rate (fraction of samples crossing zero).

    Returns:
        Arousal contribution in [-1, 1].
    """
    return _normalise(zcr, _AROUSAL_ZCR_LO, _AROUSAL_ZCR_HI)


def _rms_to_arousal(rms: float) -> float:
    """Map RMS energy onto the arousal axis.

    Args:
        rms: Root-mean-square amplitude in [0, 1].

    Returns:
        Arousal contribution in [-1, 1].
    """
    return _normalise(rms, _AROUSAL_RMS_LO, _AROUSAL_RMS_HI)


def _centroid_to_valence(centroid: float) -> float:
    """Map mean spectral centroid onto the valence axis.

    Args:
        centroid: Mean spectral centroid in Hz.

    Returns:
        Valence contribution in [-1, 1]; bright material scores positive.
    """
    return _normalise(centroid, _VALENCE_CENTROID_LO, _VALENCE_CENTROID_HI)


def _lowband_to_valence(lowband: float) -> float:
    """Map low-band energy fraction onto the valence axis.

    Args:
        lowband: Fraction of spectral energy in the sub-250 Hz band.

    Returns:
        Valence contribution in [-1, 1]; dark/muddy material scores negative.
    """
    return -_normalise(lowband, _VALENCE_LOWBAND_LO, _VALENCE_LOWBAND_HI)


def _mode_to_valence(key: str, strength: float) -> float:
    """Contribute the modality component of valence.

    Args:
        key:      Detected key string.  Major keys have no ``m`` suffix,
                  minor keys end in ``m`` (key_engine convention).
        strength: Dominance of the mode vote in [0, 1].

    Returns:
        Valence contribution in [-1, 1] scaled by the vote strength.
    """
    is_minor = key.endswith("m") and not key.endswith("maj")
    direction = _VALENCE_MINOR_WEIGHT if is_minor else _VALENCE_MAJOR_WEIGHT
    return direction * float(np.clip(strength, 0.0, 1.0))


def _as_scalar(value: object, default: float) -> float:
    """Coerce a numpy scalar/array or plain float to a Python float.

    Args:
        value:   Value returned by librosa (may be array-like).
        default: Fallback when *value* is empty.

    Returns:
        A single float.
    """
    if isinstance(value, np.ndarray):
        return float(value[0]) if len(value) > 0 else default
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    return default


def _assign_energy_band(arousal: float) -> int:
    """Discretise an arousal score into the 1..6 energy band used by the suite.

    Args:
        arousal: Arousal score in [-1, 1].

    Returns:
        Integer band from 1 (calm) to 6 (very energetic).
    """
    raw = int((arousal + 1.0) * 2.5) + 1
    return int(np.clip(raw, 1, 6))


def _valence_band(valence: float) -> int:
    """Map a valence score to a 0..3 band (0 = most negative).

    Args:
        valence: Valence in [-1, 1].

    Returns:
        Band index 0..3.
    """
    band = int(np.clip((valence + 1.0) / 2.0 * _QUADRANT_COL, 0, _QUADRANT_COL))
    return int(min(band, _QUADRANT_COL - 1))


def _arousal_band(arousal: float) -> int:
    """Map an arousal score to a 0..3 band (0 = calmest).

    Args:
        arousal: Arousal in [-1, 1].

    Returns:
        Band index 0..3.
    """
    band = int(np.clip((arousal + 1.0) / 2.0 * _QUADRANT_ROW, 0, _QUADRANT_ROW))
    return int(min(band, _QUADRANT_ROW - 1))


def _rank_mood_words(v_idx: int, a_idx: int) -> tuple[str, str, str]:
    """Return the top-3 mood words for a quadrant cell, ranked by closeness.

    Args:
        v_idx: Valence band index 0..3 (0 = most negative).
        a_idx: Arousal band index 0..3 (0 = calmest).

    Returns:
        A 3-tuple of distinct mood words, most central first.
    """
    winner = _MOOD_MATRIX[a_idx][v_idx]
    sequence: tuple[str, ...] = _MOOD_RANKING.get(winner, ("Neutral", "Calm"))
    ranked: list[str] = []
    for word in sequence:
        if word not in ranked:
            ranked.append(word)
        if len(ranked) >= _EXPECTED_WORD_COUNT:
            break
    while len(ranked) < _EXPECTED_WORD_COUNT:
        ranked.append("Neutral")
    return ranked[0], ranked[1], ranked[2]


# ── Feature extraction helpers ────────────────────────────────────────────────


def _mean_flux(y: npt.NDArray[np.float64], sr: int) -> float:
    """Return the mean spectral-flux onset strength.

    Args:
        y:  Audio signal.
        sr: Sample rate.

    Returns:
        Mean per-frame onset strength.
    """
    import librosa

    onset = librosa.onset.onset_strength(y=y, sr=sr)
    return float(np.mean(onset))


def _mean_zcr(y: npt.NDArray[np.float64]) -> float:
    """Return the mean zero-crossing rate.

    Args:
        y: Audio signal.

    Returns:
        Mean ZCR (fraction of samples crossing zero).
    """
    import librosa

    zcr = librosa.feature.zero_crossing_rate(y=y)
    return float(np.mean(zcr))


def _mean_centroid(y: npt.NDArray[np.float64], sr: int) -> float:
    """Return the mean spectral centroid in Hz.

    Args:
        y:  Audio signal.
        sr: Sample rate.

    Returns:
        Mean centroid in Hz.
    """
    import librosa

    spectral = librosa.feature.spectral_centroid(y=y, sr=sr)
    return float(np.mean(spectral))


def _lowband_energy(y: npt.NDArray[np.float64], sr: int) -> float:
    """Return the fraction of spectral energy below 250 Hz.

    Args:
        y:  Audio signal.
        sr: Sample rate.

    Returns:
        Fraction in [0, 1].
    """
    import librosa

    s = np.abs(librosa.stft(y=y))
    n_fft = 2 * (s.shape[0] - 1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    total = float(np.sum(s)) + 1.0e-12
    low = float(np.sum(s[freqs <= 250.0, :]))
    return low / total


def _compute_confidence(
    key_strength: float, flux: float, valence: float, arousal: float
) -> float:
    """Compute an overall confidence score in [0, 1].

    Confidence is higher when the acoustic features are decisive: a strong
    modal vote, pronounced spectral activity, and extreme valence/arousal.

    Args:
        key_strength: Dominance of the mode vote in [0, 1].
        flux:         Mean spectral flux.
        valence:      Final valence score in [-1, 1].
        arousal:      Final arousal score in [-1, 1].

    Returns:
        Confidence in [0, 1].
    """
    key_factor: float = 0.5 + 0.5 * float(np.clip(key_strength, 0.0, 1.0))
    flux_factor: float = float(np.clip(flux / _AROUSAL_FLUX_HI, 0.0, 1.0))
    distance: float = (abs(valence) + abs(arousal)) / 2.0
    score: float = 0.4 * key_factor + 0.3 * flux_factor + 0.3 * (0.4 + 0.6 * distance)
    return float(np.clip(score, 0.1, 1.0))


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_mood(y: npt.NDArray[np.float64], sr: int) -> MoodAnalysis:
    """Analyse the mood of a mono audio signal.

    Args:
        y:  Audio time-series (mono, float64) in [-1, 1].
        sr: Sample rate in Hz.

    Returns:
        A MoodAnalysis with valence/arousal scores, ranked mood words and an
        overall confidence estimate.

    Raises:
        AudioAnalysisError: If *y* is empty or effectively silent.
    """
    if len(y) == 0:
        raise AudioAnalysisError(
            "analyze_mood received an empty signal; mood analysis is undefined."
        )
    if np.sqrt(float(np.mean(np.square(y)))) < 1.0e-4:
        raise AudioAnalysisError(
            "analyze_mood received a near-silent signal; mood analysis is "
            "undefined for silent audio."
        )

    import librosa

    from key_detector.core.key_engine import detect_key_with_strength

    # ── Arousal features ──────────────────────────────────────────────────────
    tempo_raw, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo: float = _as_scalar(tempo_raw, default=120.0)
    rms = float(np.sqrt(np.mean(np.square(y))))
    flux = _mean_flux(y, sr)
    zcr = _mean_zcr(y)

    arousal_raw = (
        0.45 * _tempo_to_arousal(tempo)
        + 0.20 * _flux_to_arousal(flux)
        + 0.15 * _zcr_to_arousal(zcr)
        + 0.20 * _rms_to_arousal(rms)
    )
    arousal: float = float(np.clip(arousal_raw, -1.0, 1.0))

    # ── Valence features ──────────────────────────────────────────────────────
    key, key_strength = detect_key_with_strength(y, sr)
    centroid = _mean_centroid(y, sr)
    lowband = _lowband_energy(y, sr)

    valence_raw = (
        0.50 * _mode_to_valence(key, key_strength)
        + 0.30 * _centroid_to_valence(centroid)
        + 0.20 * _lowband_to_valence(lowband)
    )
    valence: float = float(np.clip(valence_raw, -1.0, 1.0))

    # ── Map to circumplex cell and words ──────────────────────────────────────
    v_idx = _valence_band(valence)
    a_idx = _arousal_band(arousal)
    mood_words = _rank_mood_words(v_idx, a_idx)
    energy = _assign_energy_band(arousal)
    confidence = _compute_confidence(key_strength, flux, valence, arousal)

    logger.debug(
        "mood: valence=%.3f arousal=%.3f words=%s confidence=%.3f energy=%d "
        "key=%s tempo=%.1f",
        valence,
        arousal,
        mood_words,
        confidence,
        energy,
        key,
        tempo,
    )
    return MoodAnalysis(
        valence=valence,
        arousal=arousal,
        mood_words=mood_words,
        confidence=confidence,
        energy=energy,
    )
