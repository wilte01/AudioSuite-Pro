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

One consequence to be aware of: when the vote is not defensible
:func:`detect_key` returns :data:`UNKNOWN_KEY`, and
``key_detector.core.file_processor`` deliberately does **not** write that to a
file's KEY tag (iteration-6 B3). The file's existing tags are left exactly as
they are and the run reports ``[DETECTED (not tagged)]``. Material with no
defensible key is therefore reported rather than tagged, instead of receiving
a fabricated key or a permanent ``"Unknown"`` in the library.

Since the 2026-10 F3 calibration, "defensible" is the *conjunction* of two
independent gates rather than a single margin threshold, and the signal is
centred first:

* The signal is de-meaned before the constant-Q transform. A pure DC offset
  carries no pitch information but leaks into the lowest CQT bins and can
  masquerade as a tonal centre: the ``np.ones`` fixture scored a margin
  confidence of 0.180 — above six of the twelve tracks in the real-music
  report that triggered F3. Centring is a no-op for real audio (already
  zero-mean) and reproduces every pinned fixture to the 4th decimal.
* The fallback fires only when the margin confidence is below the threshold
  **and** there is no clear tonal centre, where the tonal centre is the
  winning key's lead over the *average* key rather than the runner-up. Real
  music with an ambiguous modal vote (winner over runner-up near zero) is
  therefore named instead of dropped, which is what the reported directory
  exposed: seven of twelve tracks had real tonal centres but margins of only
  0.001-0.015, so a margin-only gate could never name them.

Changed in 1.0.1: recalibrates the keyless low-confidence fallback on a key-clarity
statistic.
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
#: fallback is reported instead — but only when the tonality gate
#: (:data:`CLARITY_FLOOR`) is also unsatisfied. 0.25 sits in the gap between
#: the highest measured atonal case under the old margin-only rule (a DC
#: offset, confidence 0.180) and the lowest measured genuine one (a bare
#: monophone, confidence 0.286). It deliberately leans toward the tonal
#: side — declining to name a key when the material really has one is the
#: worse failure for a key detector than reporting a low-confidence guess.
DEFAULT_LOW_CONFIDENCE_THRESHOLD: float = 0.25

#: Lowest acceptable tonal clarity for material whose key vote is ambiguous.
#: Clarity is the winning key's correlation minus the *average* correlation
#: across all 24 rotations — how far one key stands out from a split vote.
#: It is computed from the cosine scores regardless of the selected
#: correlation method, because Pearson's noise scores are documented as
#: unstable (see :data:`DEFAULT_CORRELATION`) and would otherwise make the
#: tonality gate as unreliable as the margin it backstops.
#:
#: The floor sits between the measured atonal band and the real-music band
#: (measured cosine clarity, 3 s fixtures and 90 s real tracks): broadband
#: noise ranges 0.009-0.017 and every other atonal family tested (impulse,
#: brown and band-limited noise, a sweep) stays below 0.028, while real
#: music with a genuine (if ambiguous) key measures 0.047-0.145. A synthetic
#: DC offset measures 0.044 in the raw signal, which is why the signal is
#: de-meaned first — after centring it measures exactly 0.0.
CLARITY_FLOOR: float = 0.035

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
            the fallback was reported.
        confidence: Strength of the winning vote in ``[0, 1]``, derived from
            the winning correlation's margin over the runner-up. Low for
            ambiguous material by construction.
        winner_correlation: Correlation of the winning key's profile.
        runner_up_correlation: Correlation of the best *other* key across
            all 24 rotations — the value the margin is measured against.
        clarity: The winning key's lead over the *average* correlation,
            i.e. how far one key stands out from a split vote. Computed from
            the cosine scores (method-independent). The tonality gate: a key
            with clarity below :data:`CLARITY_FLOOR` is not named even when
            the margin confidence clears the threshold.
        is_low_confidence: Whether the fallback was reported.
    """

    key: str
    confidence: float
    winner_correlation: float
    runner_up_correlation: float
    clarity: float
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

    # Remove any DC offset before the constant-Q transform. A constant (or
    # near-constant) offset carries no pitch information but leaks into the
    # lowest CQT bins, where it can masquerade as a tonal centre (the F3
    # np.ones fixture scored a margin confidence of 0.180 — above six of the
    # twelve real tracks in the report). De-meaning is a no-op for real
    # audio (already zero-mean) and is how the benchmark fixtures keep their
    # pinned values to the 4th decimal.
    y_f64 = y_f64 - float(np.mean(y_f64))

    # A pure DC offset is now exactly zero: no spectral content, hence no
    # defensible key. Short-circuit rather than sending zeroes into the CQT.
    if not np.any(y_f64):
        return KeyAnalysis(
            key=UNKNOWN_KEY,
            confidence=0.0,
            winner_correlation=0.0,
            runner_up_correlation=0.0,
            clarity=0.0,
            is_low_confidence=True,
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

    # Tonal clarity: how far the winning key stands out from the *average*
    # key. This is the tonality gate (see :data:`CLARITY_FLOOR`) and it must
    # not be derived from the selected scoring method, because Pearson's
    # noise scores are documented as unstable — measured across four noise
    # seeds Pearson's winner-minus-mean for pure broadband noise is 0.53,
    # high enough to name noise as tonal. Cosine gives 0.012 for the same
    # material, so clarity always comes from the cosine scores.
    if correlation == "cosine":
        tonality_scores: npt.NDArray[np.float64] = scores
    else:
        tonality_scores = _all_correlations(profile, "cosine")
    clarity: float = float(np.max(tonality_scores) - np.mean(tonality_scores))

    is_major: bool = winner_index < 12
    tonic_index: int = winner_index if is_major else winner_index - 12
    key: str = _display_name(tonic_index, is_major)

    scale: float = _MARGIN_SCALE[correlation]
    margin: float = winner - runner_up
    confidence: float = float(np.clip(margin / scale, 0.0, 1.0))

    # Fallback requires BOTH gates to fail: the vote is ambiguous (margin
    # below the threshold) AND the material has no clear tonal centre
    # (clarity below the floor). Either gate alone is enough to name the
    # key — that is the F3 fix, which exists because real music with a
    # genuine but ambiguous modal vote (winner over runner-up near zero)
    # was being dropped by the margin threshold alone.
    is_low_confidence: bool = (
        confidence < low_confidence_threshold and clarity < CLARITY_FLOOR
    )
    if is_low_confidence:
        logger.debug(
            "key: low confidence %.3f (margin %.4f, tone clarity %.4f, "
            "threshold %.3f); reporting %s",
            confidence,
            margin,
            clarity,
            low_confidence_threshold,
            UNKNOWN_KEY,
        )
        key = UNKNOWN_KEY

    return KeyAnalysis(
        key=key,
        confidence=confidence,
        winner_correlation=winner,
        runner_up_correlation=runner_up,
        clarity=clarity,
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
        1. Centre the signal (DC-offset removal) and build a chromagram via
           constant-Q transform.
        2. Collapse it to a 12-element pitch-class profile using *weighting*.
        3. Correlate that profile against all 24 key templates (12 major +
          12 minor rotations of the K-S profiles) using *correlation*.
        4. Report the best rotation, with a confidence taken from its margin
           over the runner-up and a tonal clarity taken from its lead over
           the average key.

    Args:
        y:   Audio time-series (mono, float64).  A zero-energy signal
             (silence) raises before correlation.
        sr:  Sample rate in Hz.
        correlation: ``"cosine"`` (default) or ``"pearson"``. See
            :data:`DEFAULT_CORRELATION` for why cosine is the default.
        weighting: ``"uniform"`` (default flat mean) or ``"energy"``.
        low_confidence_threshold: Below this margin confidence the vote is
            ambiguous — but the fallback is only reported when the signal
            also lacks a clear tonal centre (:data:`CLARITY_FLOOR`).
            Material that is ambiguous on margin but tonally clear (e.g.
            real music whose strongest two keys split the vote) is named.

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
        low_confidence_threshold: Below this *margin* confidence the vote is
            ambiguous. The fallback is reported only when the material also
            lacks a clear tonal centre (:data:`CLARITY_FLOOR`); tonally
            clear material is named even when its margin is small. Callers
            must not treat :data:`UNKNOWN_KEY` as a taggable value: it means
            "no vote", not a key.  ``key_detector.core.file_processor``
            therefore leaves the file's tags untouched and reports the
            detection only.

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
          :data:`UNKNOWN_KEY` for material with neither a decisive vote nor
          a clear tonal centre.
        * *strength* — the confidence in ``[0, 1]``: how far the winning
          correlation leads the runner-up, saturated at a fully decisive
          margin. Ambiguous material scores near 0, decisive material near
          1. Callers that weight a decision by this value therefore
          automatically down-weight an ``"Unknown"`` result. Note that a
          named key can still carry a low strength: real music whose modal
          vote is ambiguous but whose tonal centre is clear is named by the
          clarity gate while the strength reflects the split vote.

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
