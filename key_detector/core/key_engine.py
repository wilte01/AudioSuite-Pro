"""
key_engine.py
Musical key detection using chromagram analysis and
Krumhansl-Schmuckler key profiles.

Pure function — no tkinter imports, no file I/O.
Accepts a pre-loaded audio signal (numpy array + sample rate)
and returns a key string such as 'Am', 'F#', 'Eb'.
"""

import logging

import librosa
import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import AudioAnalysisError

logger = logging.getLogger(__name__)

# ── Note names ────────────────────────────────────────────────────────────────

_KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ── Display-notation overrides (DJ/pop convention) ───────────────────────────
# _KEYS above is the internal sharp-only pitch-class table used for chroma
# correlation and must not be changed (it indexes _MAJOR_PROFILE/_MINOR_PROFILE
# via np.roll). These dicts translate only the *final* returned string to the
# conventional spelling for mainstream DJ/pop usage. Major and minor are
# intentionally different mappings: e.g. G# major is conventionally written
# Ab major, but its relative-minor namesake G# minor is conventionally left
# as G#m (G#m is the standard relative minor of B major; Abm is comparatively
# rare outside classical contexts). Not every sharp pitch class is remapped —
# C# and F# are left as-is for both major and minor since sharp spelling
# dominates common DJ/pop/rock usage for those two keys.
_MAJOR_DISPLAY_OVERRIDES: dict[str, str] = {
    "D#": "Eb",
    "G#": "Ab",
    "A#": "Bb",
}

_MINOR_DISPLAY_OVERRIDES: dict[str, str] = {
    "D#": "Eb",
    "A#": "Bb",
}

# ── Krumhansl-Schmuckler key profiles ─────────────────────────────────────────
# These represent the expected pitch-class strength distribution for
# major and minor keys respectively.  Correlating an audio pitch-class
# profile against each rotation of these templates gives the best-fit key.

_MAJOR_PROFILE: npt.NDArray[np.float64] = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    dtype=np.float64,
)

_MINOR_PROFILE: npt.NDArray[np.float64] = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    dtype=np.float64,
)


# ── Public API ────────────────────────────────────────────────────────────────


def detect_key(y: npt.NDArray[np.float64], sr: int) -> str:
    """
    Detect the musical key of an audio signal.

    Algorithm:
        1. Build a chromagram via constant-Q transform.
        2. Average across time to produce a 12-element pitch-class profile.
        3. Correlate the profile against all 24 key templates
           (12 major + 12 minor rotations of the K-S profiles).
        4. Return the key with the highest correlation coefficient.

    Args:
        y:   Audio time-series (mono, float64).  A zero-energy signal
             (silence) is detected before correlation and raises ValueError.
        sr:  Sample rate in Hz.

    Returns:
        Key string in standard notation, e.g. 'Am', 'F#', 'Eb'.
        Major keys: bare letter, flat-spelled where conventional
        ('C', 'F#', 'Eb', 'Ab', 'Bb').
        Minor keys: letter + 'm', flat-spelled where conventional
        ('Am', 'F#m', 'Ebm', 'G#m', 'Bbm').

    Raises:
        ValueError: If *y* contains no energy (all-zero / pure silence),
                    making key detection undefined.
    """
    # Promote to float64 for full-precision internal processing.
    y_f64: npt.NDArray[np.float64] = y.astype(np.float64)

    # Guard: np.corrcoef on a constant vector returns NaN, producing a
    # silent, meaningless result.  Raise explicitly instead.
    if not np.any(y_f64):
        raise AudioAnalysisError(
            "detect_key received a zero-energy signal; key detection is undefined "
            "for silent audio."
        )

    chroma: npt.NDArray[np.float64] = librosa.feature.chroma_cqt(y=y_f64, sr=sr).astype(
        np.float64
    )
    chroma_avg: npt.NDArray[np.float64] = np.mean(chroma, axis=1)

    maj_correlations: list[float] = [
        float(np.corrcoef(chroma_avg, np.roll(_MAJOR_PROFILE, i))[0, 1])
        for i in range(12)
    ]
    min_correlations: list[float] = [
        float(np.corrcoef(chroma_avg, np.roll(_MINOR_PROFILE, i))[0, 1])
        for i in range(12)
    ]

    max_maj: float = max(maj_correlations)
    max_min: float = max(min_correlations)

    if max_maj >= max_min:
        sharp_key: str = _KEYS[int(np.argmax(maj_correlations))]
        return _MAJOR_DISPLAY_OVERRIDES.get(sharp_key, sharp_key)

    sharp_key = _KEYS[int(np.argmax(min_correlations))]
    return _MINOR_DISPLAY_OVERRIDES.get(sharp_key, sharp_key) + "m"


def detect_key_with_strength(y: npt.NDArray[np.float64], sr: int) -> tuple[str, float]:
    """Detect the musical key and how decisive that vote is.

    A single chroma pass is reused for both results, so callers that need
    both (e.g. mood analysers weighting a major/minor valence offset) do
    not pay twice for the constant-Q transform.

    Args:
        y:  Audio time-series (mono, float64).  A zero-energy signal raises
            ValueError like :func:`detect_key`.
        sr: Sample rate in Hz.

    Returns:
        Two-tuple ``(key, strength)``:
        * *key* — the same display string :func:`detect_key` returns
          (``'Eb'``, ``'F#m'``, ...).
        * *strength* — a float in [0, 1] approximating how separated the
          winning modality's best correlation is from the rival modality's,
          scaled so decisive tracks score close to 1 and ambiguous ones
          near 0.

    Raises:
        ValueError: If *y* contains no energy (all-zero / pure silence).
    """
    y_f64: npt.NDArray[np.float64] = y.astype(np.float64)
    if not np.any(y_f64):
        raise AudioAnalysisError(
            "detect_key_with_strength received a zero-energy signal; key "
            "detection is undefined for silent audio."
        )

    chroma: npt.NDArray[np.float64] = librosa.feature.chroma_cqt(y=y_f64, sr=sr).astype(
        np.float64
    )
    chroma_avg: npt.NDArray[np.float64] = np.mean(chroma, axis=1)

    maj_correlations: list[float] = [
        float(np.corrcoef(chroma_avg, np.roll(_MAJOR_PROFILE, i))[0, 1])
        for i in range(12)
    ]
    min_correlations: list[float] = [
        float(np.corrcoef(chroma_avg, np.roll(_MINOR_PROFILE, i))[0, 1])
        for i in range(12)
    ]

    max_maj: float = max(maj_correlations)
    max_min: float = max(min_correlations)

    if max_maj >= max_min:
        sharp_key: str = _KEYS[int(np.argmax(maj_correlations))]
        key = _MAJOR_DISPLAY_OVERRIDES.get(sharp_key, sharp_key)
    else:
        sharp_key = _KEYS[int(np.argmax(min_correlations))]
        key = _MINOR_DISPLAY_OVERRIDES.get(sharp_key, sharp_key) + "m"

    margin: float = abs(max_maj - max_min)
    strength: float = float(np.clip(0.15 + margin * 4.0, 0.0, 1.0))
    return key, strength
