"""
bpm_detector.py
Pure audio analysis logic — no tkinter dependencies.
Accepts plain Python values; returns plain Python values.

Changed in 1.1.0: uses librosa_load_with_fallback() so the new formats are analysed via
an ffmpeg transcode.
Changed in 1.4.0: failure messages are written for the user. BPMDetectionError
now subclasses AudioAnalysisError and carries a plain-language reason ("the file
may be corrupt…") instead of the decoder's text, and the stack trace is logged at
DEBUG so a corrupt file reports one line rather than a traceback.
"""

from __future__ import annotations

import logging
import os

import librosa
import numpy as np
import numpy.typing as npt

from audio_suite_shared.analysis_loader import (
    check_analysable,
    librosa_load_with_fallback,
)
from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    failure_reason,
    map_to_audio_error,
)

logger = logging.getLogger(__name__)

# Onset analysis grid, shared by the envelope and the tempo estimate so the
# periodicity check measures the same frames the tracker used.
_ONSET_HOP_LENGTH = 512

# Weights for the first four beat lags in the harmonic-comb score (one beat,
# two beats, three beats, four beats).
_HARMONIC_WEIGHTS: tuple[float, ...] = (1.0, 0.7, 0.5, 0.35)

# Minimum harmonic-comb periodicity of the onset envelope at the detected
# tempo for that tempo to be reported.  A beat repeats at its period *and* at
# multiples of it, so a real groove keeps autocorrelation energy at two, three
# and four beats; noise fitted to a tempo grid peaks at one arbitrary lag by
# chance and rarely at the whole harmonic series.
#
# Calibrated 2026-10-20 against tests/data/bpm_corpus (seven CC0 recordings,
# centre-20 s clips at 22.05 kHz): 0.154-0.595, the weakest being live jazz.
# Seeded white/pink/brown noise (600 x 30 s) scored at most 0.080.  0.10 keeps
# 1.25x headroom above the worst noise and 1.5x below the weakest real
# recording.  The previous single-lag score could not be calibrated safely:
# real music reached 0.135 while brown noise's slow drift reached 0.155, so no
# threshold separated them.  Evidence: PLAN_feature_expansion.md D79.
MIN_ONSET_PERIODICITY = 0.10


class BPMDetectionError(AudioAnalysisError):
    """Raised when BPM detection fails for any reason (IO, corrupt audio,
    librosa error).

    Subclasses :class:`AudioAnalysisError` so the shared user-message table and
    :func:`failure_reason` treat it like every other analysis failure.
    """


def _onset_periodicity(
    onset_env: npt.NDArray[np.float64],
    tempo_bpm: float,
    sr: int,
    *,
    hop_length: int = _ONSET_HOP_LENGTH,
) -> float:
    """Return how strongly the onset envelope repeats at *tempo_bpm*.

    The envelope has its mean removed and is autocorrelated; the result is
    normalised by the zero-lag energy, so the value is independent of level
    and each lag lies in [-1, 1].  The peak is taken within +/-10% of each of
    the first four beat lags, which tolerates small timing jitter and tempo
    drift.  Those peaks are combined with decreasing weights: a groove
    correlates at every multiple of its beat, while noise fitted to a tempo
    grid has no reason to correlate again two, three or four beats later.
    Scoring only the first lag could not separate real free-time music (0.135)
    from brown noise's slow drift (0.155), which is why the score is a comb.

    Args:
        onset_env: Onset-strength envelope on the analysis hop grid.
        tempo_bpm: Tempo whose period is tested, in beats per minute.
        sr:        Sample rate in Hz.
        hop_length: Hop length the envelope was computed with.

    Returns:
        Weighted harmonic-comb score, or 0.0 when the envelope carries no
        energy or no beat lag fits inside the analysed window.
    """
    if tempo_bpm <= 0.0 or len(onset_env) < 2:
        return 0.0
    centred = onset_env - float(np.mean(onset_env))
    energy = float(np.dot(centred, centred))
    if energy <= 0.0:
        return 0.0

    correlation: npt.NDArray[np.float64] = np.correlate(centred, centred, mode="full")[
        len(centred) - 1 :
    ]
    normalised = correlation / correlation[0]

    lag = 60.0 / tempo_bpm * float(sr) / float(hop_length)
    if lag < 1.0:
        return 0.0

    weighted = 0.0
    total_weight = 0.0
    for harmonic, weight in enumerate(_HARMONIC_WEIGHTS, start=1):
        harmonic_lag = lag * harmonic
        low = max(int(np.floor(harmonic_lag * 0.9)), 1)
        high = max(int(np.ceil(harmonic_lag * 1.1)) + 1, low + 1)
        if low >= len(normalised):
            break
        weighted += weight * float(np.max(normalised[low:high]))
        total_weight += weight
    if total_weight <= 0.0:
        return 0.0
    return weighted / total_weight


def _no_tempo_message(periodicity: float | None = None) -> str:
    """Build the one user-facing sentence for a beatless file.

    The onset-periodicity score is included only when it was measured: a
    non-positive tempo estimate never reached the periodicity check, so
    reporting 0.00 there would imply evidence that was never gathered.  The
    score and the minimum are what makes a skip auditable in the per-file log
    and status line, instead of a bare verdict.

    Args:
        periodicity: Measured onset periodicity, or None when not measured.

    Returns:
        The sentence shown for the skipped file.
    """
    message = "No tempo detected — the audio has no discernible beat"
    if periodicity is None:
        return f"{message}."
    return (
        f"{message} (onset periodicity {periodicity:.2f}, "
        f"minimum {MIN_ONSET_PERIODICITY:.2f})."
    )


class NoTempoDetectedError(BPMDetectionError):
    """Raised when the audio carries no discernible beat.

    Two distinct inputs land here.  Beatless material — a sustained tone, a
    drone, or a pad with no rhythmic transients — makes librosa's beat tracker
    report a non-positive tempo.  Noise, by contrast, yields a *positive*
    estimate because random onsets can be fitted to a tempo grid, but its
    onset envelope does not repeat at that period.  Neither is a tempo below
    the configured range: clamping either to ``min_bpm`` invented a value (the
    clamp floor) that the tool then wrote as the file's BPM tag.  The subclass
    lets the per-file processor report the outcome as a skip rather than a
    failure, while callers that catch the parent still see the declared
    ``BPMDetectionError`` contract.
    """


def detect_bpm(
    file_path: str,
    max_duration: int = 90,
    min_bpm: int = 75,
    max_bpm: int = 175,
) -> int:
    """
    Detect the BPM of an audio file using librosa beat tracking.

    Audio is loaded as 64-bit float (np.float64) for internal processing
    to prevent quantization noise accumulation.

    Args:
        file_path:    Absolute path to the audio file.
        max_duration: Maximum seconds of audio to analyse
        (trade-off: speed vs accuracy).
        min_bpm:      Lower bound for the returned BPM value.
        max_bpm:      Upper bound for the returned BPM value.

    Returns:
        Detected BPM rounded to the nearest integer, constrained to [min_bpm, max_bpm].

    Raises:
        NoTempoDetectedError: The beat tracker found no tempo (beatless audio).
        BPMDetectionError: Wraps any librosa / IO error with a descriptive message.
                           The original exception is available as __cause__.
    """
    try:
        # Load as float32 (librosa default) then upcast to float64 for DSP precision.
        y_f32: npt.NDArray[np.float32]
        y_f32, sr = librosa_load_with_fallback(
            file_path, duration=max_duration, mono=True
        )
        y: npt.NDArray[np.float64] = y_f32.astype(np.float64)
        sr = int(sr)

        # The shared loader documents a guard "so analysis engines never
        # receive degenerate input", but BPM decodes through
        # librosa_load_with_fallback directly (it needs the raw float32 path),
        # so the guard has to be applied here.  check_analysable covers both
        # halves: a 0.2 s blip was beat-tracked and tagged with the clamp
        # floor, and digital silence produced the same fabricated BPM because
        # beat tracking reports tempo 0 on a flat signal.
        check_analysable(y, sr)

        logger.debug(
            "Loaded '%s': %d samples @ %d Hz (%.1f s)",
            file_path,
            len(y),
            sr,
            len(y) / sr,
        )

        # Compute the onset envelope once and hand it to the tracker: the
        # periodicity check below needs the same frames, and passing the
        # envelope avoids a second STFT pass.
        onset_env: npt.NDArray[np.float64] = librosa.onset.onset_strength(
            y=y, sr=sr, hop_length=_ONSET_HOP_LENGTH, aggregate=np.median
        )
        tempo_raw, _ = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, hop_length=_ONSET_HOP_LENGTH
        )

        # librosa may return a numpy array; normalise to a scalar float.
        tempo: float
        if isinstance(tempo_raw, np.ndarray):
            tempo = float(tempo_raw[0]) if len(tempo_raw) > 0 else 120.0
        else:
            tempo = float(tempo_raw)

        logger.debug("Raw tempo estimate for '%s': %.2f BPM", file_path, tempo)

        # A non-positive (or non-finite) estimate means the beat tracker found
        # no beat at all — a sustained tone, a drone, or a pad with no rhythmic
        # transients.  Doubling zero stays zero, so octave correction used to
        # skip it and the hard clamp turned it into the floor: a fabricated
        # value the tool then tagged.  Report the absence of a beat instead.
        if not np.isfinite(tempo) or tempo <= 0.0:
            logger.debug(
                "No tempo detected for '%s': raw estimate %r", file_path, tempo
            )
            raise NoTempoDetectedError(
                _no_tempo_message(),
                context={"tempo_estimate": tempo},
            )

        # A positive estimate can still be spurious: the tracker fits a tempo
        # grid to random onsets in noise.  Only report a tempo whose period is
        # actually present in the onset envelope.
        periodicity = _onset_periodicity(onset_env, tempo, sr)
        logger.debug(
            "Onset periodicity for '%s' at %.2f BPM: %.3f (minimum %.2f)",
            file_path,
            tempo,
            periodicity,
            MIN_ONSET_PERIODICITY,
        )
        if periodicity < MIN_ONSET_PERIODICITY:
            raise NoTempoDetectedError(
                _no_tempo_message(periodicity),
                context={
                    "tempo_estimate": tempo,
                    "onset_periodicity": periodicity,
                },
            )

        # Octave-correct: double/halve until inside the requested range.
        while tempo < min_bpm and tempo * 2 <= max_bpm:
            tempo *= 2
        while tempo > max_bpm and tempo / 2 >= min_bpm:
            tempo /= 2

        # Hard clamp as a final safety net.
        tempo = max(float(min_bpm), min(float(max_bpm), tempo))
        result: int = round(tempo)

        logger.info("BPM detected for '%s': %d", file_path, result)
        return result

    except NoTempoDetectedError:
        # Absence of a beat is an outcome, not a failure: re-raise the subclass
        # unchanged so the per-file processor can report a skip.  The broad
        # handler below would otherwise re-wrap it as a generic
        # BPMDetectionError and turn the skip back into an error.
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": file_path, "operation": "detect_bpm"}
        )
        reason = failure_reason(mapped)
        # The caller (the per-file worker, or a direct library user) is the
        # boundary that reports the outcome; logging at DEBUG here keeps one
        # ERROR line per failed file instead of the same failure twice.
        logger.debug(
            "[%s] BPM detection failed for '%s': %s",
            type(mapped).__name__,
            os.path.basename(file_path),
            reason,
            exc_info=exc,
        )
        raise BPMDetectionError(reason) from exc
