"""
key_engine.py
Musical key detection using chromagram analysis and
Krumhansl-Schmuckler key profiles.

Pure function — no tkinter imports, no file I/O.
Accepts a pre-loaded audio signal (numpy array + sample rate)
and returns a key string such as 'Am', 'F#', 'Eb'.

Plan iteration 5, item F2 (audit #7).  The engine is unchanged in *what* it
scores — the shipped Krumhansl-Schmuckler profiles are used exactly as they
were, deliberately not re-tuned against the F1 fixtures — but the scoring
path is now parameterised and the result carries an honest confidence:

* :func:`analyze_key` returns a :class:`KeyAnalysis` with the key, a
  confidence derived from the winning correlation's margin over the
  runner-up, and the two correlations themselves.
* :func:`detect_key` and :func:`detect_key_with_strength` keep their
  original signatures and delegate to it. The second element of
  ``detect_key_with_strength`` is now the stated confidence, which is what
  the mood analyser already weights its key-derived valence offset by.
* Material with no defensible key (measured: broadband white noise) no
  longer yields a fabricated one; it yields :data:`UNKNOWN_KEY`.

Two knobs are exposed so the algorithm can be tuned without editing it:

* ``correlation`` — how the chroma vector is compared to each profile
  rotation (``"cosine"`` default, ``"pearson"`` for the historical
  behaviour). The choice is not cosmetic: Pearson still resolves every
  chromatic triad, but its margin for white noise is unstable enough to
  fabricate confident keys, so it is retained for compatibility rather than
  recommended. See :data:`DEFAULT_CORRELATION`.
* ``weighting`` — how frames are collapsed into the 12-bin pitch-class
  profile (``"uniform"`` = flat mean, ``"energy"`` = energy-weighted).

One consequence to be aware of: ``key_detector.core.file_processor`` writes
whatever :func:`detect_key` returns straight to a file's KEY tag, so
untuned material will now be tagged ``"Unknown"`` rather than given a
fabricated key. Filtering that out at the tag writer is deliberately out of
this item's scope.
"""

import logging
from dataclasses import dataclass
from typing import Literal

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
#
# The values are the published K-S profiles and are intentionally NOT
# re-tuned (plan F2: "Do not re-tune the profiles against the F1 fixtures.
# Tuning on the test vectors and then reporting those vectors as validation
# is circular").

_MAJOR_PROFILE: npt.NDArray[np.float64] = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
    dtype=np.float64,
)

_MINOR_PROFILE: npt.NDArray[np.float64] = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    dtype=np.float64,
)

# ── Tunables (F2) ─────────────────────────────────────────────────────────────

CorrelationMethod = Literal["pearson", "cosine"]
Weighting = Literal["uniform", "energy"]

#: Returned instead of a key when the vote is not decisive enough to defend.
#: Matches the existing convention in ``tempo_analyzer``'s ``get_tempo_marking``,
#: which also returns ``"Unknown"`` when its lookup cannot justify a value.
UNKNOWN_KEY: str = "Unknown"

#: Default correlation. Cosine is the default because it is the only one of
#: the two whose winner-to-runner-up margin actually separates tonal from
#: atonal material. Measured on the F1 fixture families: with Pearson,
#: white-noise margins overlap major-triad margins, and across four seeds of
#: pure white noise Pearson names a key for two of them and calls it
#: confident ('Em' at 0.8995, 'C#m' at 0.6565) — no threshold can rescue a
#: margin that unstable. With cosine the same families measure 0.0007-0.0024
#: (noise) versus 0.053-0.068 (triads) and 0.037-0.063 (progressions), and
#: every noise seed falls back.
DEFAULT_CORRELATION: CorrelationMethod = "cosine"

#: Default frame weighting: the flat mean, i.e. today's behaviour.
DEFAULT_WEIGHTING: Weighting = "uniform"

#: Confidence at or above this is reported as a real key; below it the
#: fallback is reported instead. 0.25 sits in the gap between the highest
#: measured atonal case (a DC offset, confidence 0.180) and the lowest
#: measured genuine one (a bare monophone, confidence 0.286). It deliberately
#: leans toward the tonal side — declining to name a key when the material
#: really has one is the worse failure for a key detector than reporting a
#: low-confidence guess.
DEFAULT_LOW_CONFIDENCE_THRESHOLD: float = 0.25

#: Correlation margin treated as a fully decisive vote, per method. These are
#: round numbers deliberately set ABOVE the measured margin band of real
#: musical material rather than fitted to it, so that confidence saturates
#: for genuine keys instead of tracking a particular fixture. Pearson needs
#: the larger scale because its margins for the same material are roughly
#: three times cosine's.
_MARGIN_SCALE: dict[CorrelationMethod, float] = {
    "cosine": 0.08,
    "pearson": 0.20,
}


@dataclass(frozen=True)
class KeyAnalysis:
    """The outcome of a key-detection pass.

    Attributes:
        key: Detected key in display notation, or :data:`UNKNOWN_KEY` when
            the confidence fell below the low-confidence threshold.
        confidence: Strength of the winning vote in ``[0, 1]``, derived from
            the winning correlation's margin over the runner-up. Low for
            ambiguous material by construction.
        winner_correlation: Correlation of the winning key's profile.
        runner_up_correlation: Correlation of the best *other* key across
            all 24 rotations — the value the margin is measured against.
        is_low_confidence: Whether the fallback was reported.
    """

    key: str
    confidence: float
    winner_correlation: float
    runner_up_correlation: float
    is_low_confidence: bool


# ── Scoring internals ─────────────────────────────────────────────────────────


def _correlation(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], method: CorrelationMethod
) -> float:
    """Correlation coefficient between two 12-bin profiles.

    ``"pearson"`` is the historical ``np.corrcoef`` behaviour. ``"cosine"``
    measures alignment only, ignoring overall magnitude, which is why its
    margins are smaller and better separated.
    """
    if method == "pearson":
        value: float = float(np.corrcoef(a, b)[0, 1])
        return 0.0 if np.isnan(value) else value
    norm_a: float = float(np.linalg.norm(a))
    norm_b: float = float(np.linalg.norm(b))
    if norm_a <= 1.0e-12 or norm_b <= 1.0e-12:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _pitch_class_profile(
    chroma: npt.NDArray[np.float64], weighting: Weighting
) -> npt.NDArray[np.float64]:
    """Collapse a ``(12, frames)`` chromagram into one 12-bin profile.

    ``"uniform"`` is the flat frame mean. ``"energy"`` weights each frame by
    its own chroma energy, so loud, harmonically active frames dominate the
    vote instead of being averaged away against near-silent ones.
    """
    if weighting == "uniform":
        profile: npt.NDArray[np.float64] = np.mean(chroma, axis=1)
        return profile
    weights: npt.NDArray[np.float64] = np.sum(chroma, axis=1)
    total: float = float(np.sum(weights))
    if total <= 1.0e-12:
        degenerate: npt.NDArray[np.float64] = np.mean(chroma, axis=1)
        return degenerate
    weighted: npt.NDArray[np.float64] = (
        np.sum(chroma * weights[:, None], axis=1) / total
    )
    return weighted


def _all_correlations(
    profile: npt.NDArray[np.float64], method: CorrelationMethod
) -> npt.NDArray[np.float64]:
    """Score *profile* against all 12 major then 12 minor rotations.

    Returns a length-24 vector; indices 0-11 are major rotations and 12-23
    are minor rotations, in ``_KEYS`` order.
    """
    major: npt.NDArray[np.float64] = np.array(
        [_correlation(profile, np.roll(_MAJOR_PROFILE, i), method) for i in range(12)],
        dtype=np.float64,
    )
    minor: npt.NDArray[np.float64] = np.array(
        [_correlation(profile, np.roll(_MINOR_PROFILE, i), method) for i in range(12)],
        dtype=np.float64,
    )
    return np.concatenate([major, minor])


def _display_name(index: int, is_major: bool) -> str:
    sharp: str = _KEYS[index]
    if is_major:
        return _MAJOR_DISPLAY_OVERRIDES.get(sharp, sharp)
    return _MINOR_DISPLAY_OVERRIDES.get(sharp, sharp) + "m"


def _analyse(
    y: npt.NDArray[np.float64],
    sr: int,
    correlation: CorrelationMethod,
    weighting: Weighting,
    low_confidence_threshold: float,
    caller: str,
) -> KeyAnalysis:
    """Single-pass analysis shared by every public entry point."""
    y_f64: npt.NDArray[np.float64] = y.astype(np.float64)

    # Guard: correlation against a constant/empty vector is undefined, so
    # raise explicitly rather than returning a meaningless key.
    if not np.any(y_f64):
        raise AudioAnalysisError(
            f"{caller} received a zero-energy signal; key detection is undefined "
            "for silent audio."
        )

    chroma: npt.NDArray[np.float64] = librosa.feature.chroma_cqt(y=y_f64, sr=sr).astype(
        np.float64
    )
    profile: npt.NDArray[np.float64] = _pitch_class_profile(chroma, weighting)
    scores: npt.NDArray[np.float64] = _all_correlations(profile, correlation)

    # The runner-up is the best key of the *opposite* modality when the two
    # rival keys share a tonic, otherwise the best key overall; taking the
    # second best of all 24 covers both and keeps the margin honest.
    order: npt.NDArray[np.int64] = np.argsort(scores)[::-1]
    winner_index: int = int(order[0])
    runner_up: float = float(scores[int(order[1])])
    winner: float = float(scores[winner_index])

    is_major: bool = winner_index < 12
    tonic_index: int = winner_index if is_major else winner_index - 12
    key: str = _display_name(tonic_index, is_major)

    scale: float = _MARGIN_SCALE[correlation]
    margin: float = winner - runner_up
    confidence: float = float(np.clip(margin / scale, 0.0, 1.0))

    is_low_confidence: bool = confidence < low_confidence_threshold
    if is_low_confidence:
        logger.debug(
            "key: low confidence %.3f (margin %.4f, threshold %.3f); reporting %s",
            confidence,
            margin,
            low_confidence_threshold,
            UNKNOWN_KEY,
        )
        key = UNKNOWN_KEY

    return KeyAnalysis(
        key=key,
        confidence=confidence,
        winner_correlation=winner,
        runner_up_correlation=runner_up,
        is_low_confidence=is_low_confidence,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def analyze_key(
    y: npt.NDArray[np.float64],
    sr: int,
    *,
    correlation: CorrelationMethod = DEFAULT_CORRELATION,
    weighting: Weighting = DEFAULT_WEIGHTING,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> KeyAnalysis:
    """Detect the key of a signal and report how defensible that answer is.

    Algorithm:
        1. Build a chromagram via constant-Q transform.
        2. Collapse it to a 12-element pitch-class profile using *weighting*.
        3. Correlate that profile against all 24 key templates (12 major +
           12 minor rotations of the K-S profiles) using *correlation*.
        4. Report the best rotation, with a confidence taken from its margin
           over the runner-up.

    Args:
        y:   Audio time-series (mono, float64).  A zero-energy signal
             (silence) raises before correlation.
        sr:  Sample rate in Hz.
        correlation: ``"cosine"`` (default) or ``"pearson"``. See
            :data:`DEFAULT_CORRELATION` for why cosine is the default.
        weighting: ``"uniform"`` (default flat mean) or ``"energy"``.
        low_confidence_threshold: Confidence at or above which a real key is
            reported; below it :data:`UNKNOWN_KEY` is reported instead.

    Returns:
        A :class:`KeyAnalysis`.

    Raises:
        AudioAnalysisError: If *y* contains no energy (all-zero / silence).
    """
    return _analyse(
        y, sr, correlation, weighting, low_confidence_threshold, "analyze_key"
    )


def detect_key(
    y: npt.NDArray[np.float64],
    sr: int,
    *,
    correlation: CorrelationMethod = DEFAULT_CORRELATION,
    weighting: Weighting = DEFAULT_WEIGHTING,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> str:
    """
    Detect the musical key of an audio signal.

    Args:
        y:   Audio time-series (mono, float64).  A zero-energy signal
             (silence) is detected before correlation and raises.
        sr:  Sample rate in Hz.
        correlation: ``"cosine"`` (default) or ``"pearson"``.
        weighting: ``"uniform"`` (default) or ``"energy"``.
        low_confidence_threshold: Below this confidence, :data:`UNKNOWN_KEY`
            is returned instead of a fabricated key.  Note that callers which
            write the result straight to a tag (see
            ``key_detector.core.file_processor``) will therefore write
            ``"Unknown"`` for material with no defensible key; that is the
            documented low-confidence behaviour, not a key.

    Returns:
        Key string in standard notation, e.g. 'Am', 'F#', 'Eb', or
        :data:`UNKNOWN_KEY` when the vote is not decisive.
        Major keys: bare letter, flat-spelled where conventional
        ('C', 'F#', 'Eb', 'Ab', 'Bb').
        Minor keys: letter + 'm', flat-spelled where conventional
        ('Am', 'F#m', 'Ebm', 'G#m', 'Bbm').

    Raises:
        AudioAnalysisError: If *y* contains no energy (all-zero / pure
            silence), making key detection undefined.
    """
    return _analyse(
        y, sr, correlation, weighting, low_confidence_threshold, "detect_key"
    ).key


def detect_key_with_strength(
    y: npt.NDArray[np.float64],
    sr: int,
    *,
    correlation: CorrelationMethod = DEFAULT_CORRELATION,
    weighting: Weighting = DEFAULT_WEIGHTING,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> tuple[str, float]:
    """Detect the key and how decisive that vote is.

    A single chroma pass is reused for both results, so callers that need
    both (e.g. the mood analyser, which weights a major/minor valence
    offset by this value) do not pay twice for the constant-Q transform.

    Args:
        y:  Audio time-series (mono, float64).  A zero-energy signal raises
            like :func:`detect_key`.
        sr: Sample rate in Hz.
        correlation: ``"cosine"`` (default) or ``"pearson"``.
        weighting: ``"uniform"`` (default) or ``"energy"``.
        low_confidence_threshold: Below this confidence, :data:`UNKNOWN_KEY`
            is returned with the (low) confidence as the second element.

    Returns:
        Two-tuple ``(key, strength)``:
        * *key* — the same display string :func:`detect_key` returns, or
          :data:`UNKNOWN_KEY` for material with no defensible key.
        * *strength* — the confidence in ``[0, 1]``: how far the winning
          correlation leads the runner-up, saturated at a fully decisive
          margin. Ambiguous material scores near 0, decisive material near
          1. Callers that weight a decision by this value therefore
          automatically down-weight an ``"Unknown"`` result.

    Raises:
        AudioAnalysisError: If *y* contains no energy (all-zero / silence).
    """
    analysis: KeyAnalysis = _analyse(
        y,
        sr,
        correlation,
        weighting,
        low_confidence_threshold,
        "detect_key_with_strength",
    )
    return analysis.key, analysis.confidence
