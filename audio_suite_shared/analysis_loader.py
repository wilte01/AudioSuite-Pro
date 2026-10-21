"""
analysis_loader.py — Shared audio loading for signal-analysis tools.

Part of audio_suite_shared. Provides a single consistent path for tools
(BPM analyser, key detector, mood analyser) to decode an audio file into a
mono, 64-bit float time series suitable for DSP, plus a silence / too-short
guard so analysis engines never receive degenerate input.

Decoding uses librosa (SoundFile-backed; on librosa <= 0.11 a corrupt
container can additionally fall back to audioread and decode to an empty
signal at ``sr == 0``, which the guard below rejects — librosa >= 1.0 removed
that fallback and raises the soundfile error instead). Samples are always
upcast to ``numpy.float64`` to avoid quantisation noise accumulation during
feature extraction.

Changed in 1.1.0: added librosa_load_with_fallback() with an ffmpeg transcode fallback
so the new containers can be analysed.
Changed in 1.4.0: an undecodable file now raises AudioCodecError with a
plain-language reason instead of re-raising the decoder's own text. libsndfile
reports an unreadable container as "File does not exist or is not a regular
file (possibly a pipe?)", which told users a file they could see had vanished;
the original exception is kept as ``__cause__`` for the log.

Changed in 1.4.1: ``warm_analysis_stack()`` compiles librosa's lazy numba
kernels once per process before a worker pool starts, so eight threads no
longer compile the same signature eight times and serialise on the compile
lock (backlog P6).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from typing import Any

import numpy as np
import numpy.typing as npt

from .exceptions import (
    AudioAnalysisError,
    AudioCodecError,
    log_handled_failure,
    map_to_audio_error,
)
from .secure_subprocess import run_secure_subprocess

logger = logging.getLogger(f"audio_suite.{__name__}")

# Below this duration (seconds) the audio is too short for meaningful
# analysis — beat tracking and pitch-class correlation are undefined.
MIN_ANALYSIS_SECONDS = 0.5

# Fraction of full-scale that counts as "effectively silent" (~ -60 dBFS).
SILENCE_RMS_THRESHOLD = 1.0e-3

#: Plain-language reason for a decode failure.  Decoders word this badly
#: (libsndfile says "File does not exist or is not a regular file" for a file
#: that plainly exists, and FFmpeg reports a negative exit code), so the
#: user-facing text is written here instead of passed through.
DECODE_FAILURE_REASON = (
    "the file may be corrupt, truncated, or in a format no available decoder can read"
)

#: Length of the synthetic warm-up signal, in seconds.  The tracker must find
#: a full beat grid (several beats, not an early exit) for the compile it does
#: on real music to happen here instead of in the first worker thread; 8 s at
#: 120 BPM gives 16 beats and still costs far less than the compile it replaces.
_WARM_UP_SECONDS = 8.0

#: Tempo of the warm-up signal.  120 BPM is the tracker's own default prior, so
#: the warm-up takes the same branch a typical track does rather than an
#: unlikely one (a 240 BPM click train took a different path).
_WARM_UP_BEAT_SECONDS = 0.5

#: Sample rate of the warm-up signal; analysis tools decode at the native rate,
#: so any rate exercises the same kernels.
_WARM_UP_SAMPLE_RATE = 22050

_warm_up_lock = threading.Lock()
_warm_up_done = False


def warm_analysis_stack() -> None:
    """Compile librosa's lazy numba kernels once, before a worker pool starts.

    librosa's STFT magnitude, chroma and beat helpers are numba ``vectorize``
    ufuncs compiled on first call.  A serial batch pays that compile once
    (~1.8 s), but a *thread* pool pays it once per worker: numba does not
    deduplicate concurrent first calls, so every thread compiles the same
    signature again and they contend for the compile lock.  On an 8-file, 30 s
    batch that turned a 1.8 s one-off into 11.3 s of wall time — the batch got
    *slower* going from 4 to 8 threads (PLAN_feature_expansion P6).

    Warming on a tiny synthetic signal in one thread before the pool starts
    collapses that to a single compile; the pool then runs on compiled kernels
    and scales the way the CPU count suggests.  Every analysis tool calls this
    at its batch entry point, so the cost is paid once per process.

    The call is idempotent and thread-safe.  A failure is logged at DEBUG and
    never raised: the warm-up is an optimisation, and the analysis that follows
    compiles the kernels itself (just without the speed-up).
    """
    global _warm_up_done
    if _warm_up_done:
        return
    with _warm_up_lock:
        if _warm_up_done:
            return
        try:
            _run_warm_up()
        except Exception:  # noqa: BLE001 - an optimisation must not fail a batch
            logger.debug(
                "librosa warm-up failed; kernels will compile lazily", exc_info=True
            )
        finally:
            # Set even on failure: retrying per file would add the cost the
            # warm-up exists to remove.
            _warm_up_done = True


def _run_warm_up() -> None:
    """Run every librosa call the analysis tools make on a synthetic signal.

    The signal is a decaying kick every 0.5 s (120 BPM) over a quiet noise bed:
    broadband onsets plus a clear beat grid.  Both halves matter — a pure-tone
    "click train" made the tracker take a different branch, so the kernels the
    real files needed were still compiled inside the pool, exactly the race this
    warm-up exists to prevent.
    """
    import librosa

    samples = int(_WARM_UP_SAMPLE_RATE * _WARM_UP_SECONDS)
    rng = np.random.default_rng(0)
    y = 0.02 * rng.standard_normal(samples)
    for beat in np.arange(0.0, _WARM_UP_SECONDS, _WARM_UP_BEAT_SECONDS):
        start = int(beat * _WARM_UP_SAMPLE_RATE)
        length = min(int(0.1 * _WARM_UP_SAMPLE_RATE), samples - start)
        if length <= 0:
            continue
        local = np.arange(length, dtype=np.float64) / _WARM_UP_SAMPLE_RATE
        envelope = np.exp(-local / 0.01)
        y[start : start + length] += 0.5 * envelope * np.sin(2 * np.pi * 90.0 * local)

    onset_env = librosa.onset.onset_strength(
        y=y, sr=_WARM_UP_SAMPLE_RATE, hop_length=512, aggregate=np.median
    )
    librosa.beat.beat_track(
        onset_envelope=onset_env, sr=_WARM_UP_SAMPLE_RATE, hop_length=512
    )
    librosa.feature.chroma_cqt(y=y, sr=_WARM_UP_SAMPLE_RATE)
    librosa.feature.zero_crossing_rate(y=y)
    librosa.feature.spectral_centroid(y=y, sr=_WARM_UP_SAMPLE_RATE)
    librosa.feature.mfcc(y=y, sr=_WARM_UP_SAMPLE_RATE)
    spectrum = librosa.stft(y=y)
    librosa.amplitude_to_db(np.abs(spectrum))
    librosa.fft_frequencies(sr=_WARM_UP_SAMPLE_RATE)
    librosa.times_like(spectrum, sr=_WARM_UP_SAMPLE_RATE, hop_length=512)
    logger.debug("librosa analysis kernels warmed (%d samples)", samples)


def decode_error(
    file_path: str, *, original: Exception | None = None
) -> AudioCodecError:
    """Build the one user-facing error for an undecodable file.

    Args:
        file_path: Path that failed to decode; only its basename is shown.
        original:  The decoder's exception, preserved as ``__cause__``.

    Returns:
        An ``AudioCodecError`` whose message names the file and the likely
        cause without repeating the decoder's internal wording.
    """
    name = os.path.basename(file_path)
    return AudioCodecError(
        f"Could not decode '{name}' — {DECODE_FAILURE_REASON}.",
        context={"file": file_path, "operation": "decode"},
        original=original,
    )


def _missing_file_error(file_path: str) -> AudioCodecError:
    """Build the user-facing error for a path that no longer exists.

    Callers catch ``AudioCodecError`` for undecodable files, so a file deleted
    between the scan and the decode keeps that contract while saying what
    actually happened.
    """
    name = os.path.basename(file_path)
    return AudioCodecError(
        f"Could not decode '{name}' — the file was not found; it may have been "
        "moved or deleted.",
        context={"file": file_path, "operation": "decode"},
    )


def librosa_load_with_fallback(
    file_path: str,
    *,
    duration: int = 0,
    mono: bool = True,
    sr: int | None = None,
) -> tuple[npt.NDArray[np.float32], int]:
    """Decode audio with librosa, transcoding via FFmpeg for formats it cannot read.

    ``librosa`` decodes through ``libsndfile``, which reads none of the
    lossless/lossy formats added in Sprint 1 (WavPack, Monkey's Audio,
    Musepack, Speex, DSF). When the direct decode raises, the file is
    transcoded to a temporary WAV with FFmpeg and re-read, so every analysis
    tool keeps working on the widened ``SUPPORTED_EXTENSIONS`` set instead of
    failing per file. The fallback is best-effort: if FFmpeg is unavailable
    or the transcode also fails, the decode is reported as an
    ``AudioCodecError`` with a plain-language reason, and the decoder's own
    exception is preserved as ``__cause__``.  A path that does not exist is
    still re-raised unchanged (no transcode can rescue it).

    Args:
        file_path: Path to the audio file.
        duration:  Maximum seconds to decode (``0`` disables the cap).
        mono:      Downmix to a single channel when True.
        sr:        Target sample rate, or None to keep the native rate.

    Returns:
        Two-tuple ``(y, sr)`` where *y* is a mono float32 array and *sr* is
        the sample rate in Hz.

    Raises:
        AudioCodecError: Neither the direct decode nor the FFmpeg transcode
            could read the file.
        Exception: The original decode error when the path does not exist.
    """
    import librosa

    try:
        y_f32, out_sr = _librosa_load(librosa, file_path, duration, mono, sr)
    except Exception as exc:
        # A non-existent path can never be rescued by FFmpeg; surface the
        # original error rather than spawning a doomed transcode.
        if not os.path.isfile(file_path):
            raise
        transcoded = _transcode_via_ffmpeg(
            file_path, duration=duration, mono=mono, sr=sr
        )
        if transcoded is None:
            raise decode_error(file_path, original=exc) from exc
        return transcoded
    return y_f32, int(out_sr)


def _librosa_load(
    librosa_module: Any,
    file_path: str,
    duration: int,
    mono: bool,
    sr: int | None,
) -> tuple[Any, Any]:
    """Call ``librosa.load`` with optional duration capping.

    Args:
        librosa_module: The imported librosa module (injectable for tests).
        file_path:      Path to the audio file.
        duration:       Maximum seconds to decode (``0`` disables the cap).
        mono:           Downmix to a single channel when True.
        sr:             Target sample rate, or None to keep the native rate.

    Returns:
        The raw ``(y_f32, sr)`` pair returned by ``librosa.load``.
    """
    if duration and duration > 0:
        capped: tuple[Any, Any] = librosa_module.load(
            file_path, duration=duration, mono=mono, sr=sr
        )
        return capped
    loaded: tuple[Any, Any] = librosa_module.load(file_path, mono=mono, sr=sr)
    return loaded


def _transcode_via_ffmpeg(
    file_path: str,
    *,
    duration: int = 0,
    mono: bool = True,
    sr: int | None = None,
) -> tuple[npt.NDArray[np.float32], int] | None:
    """Transcode *file_path* to a temporary WAV with FFmpeg and read it back.

    Args:
        file_path: Path to the audio file.
        duration:  Maximum seconds to transcode (``0`` disables the cap).
        mono:      Downmix to a single channel when True.
        sr:        Target sample rate, or None to keep the native rate.

    Returns:
        Two-tuple ``(y, sr)`` on success, or None when FFmpeg is unavailable
        or the transcode/decode fails (the caller keeps the original error).
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.debug("FFmpeg not found; no decode fallback for %s", file_path)
        return None

    import librosa

    try:
        with tempfile.TemporaryDirectory(prefix="audiosuite_analysis_") as temp_dir:
            wav_path = os.path.join(temp_dir, "transcoded.wav")
            args = ["-v", "error", "-y", "-i", file_path]
            if duration and duration > 0:
                args += ["-t", str(duration)]
            args += ["-ac", "1" if mono else "2", "-f", "wav", wav_path]
            # This transcode is a probe: a failure here is an expected outcome
            # for a corrupt file, and the caller reports it in plain language.
            # Suppressing the subprocess's own ERROR record keeps FFmpeg's
            # exit code and stderr out of the user-facing console output.
            run_secure_subprocess(
                ffmpeg,
                args,
                capture_output=True,
                check=True,
                log_failure=False,
            )
            y_f32, out_sr = _librosa_load(librosa, wav_path, 0, mono, sr)
            decoded: npt.NDArray[np.float32] = y_f32
            return decoded, int(out_sr)
    except Exception:
        logger.debug(
            "FFmpeg transcode fallback failed for %s", file_path, exc_info=True
        )
        return None


def load_analysis_audio(
    file_path: str, max_duration: int = 90, *, min_seconds: float = MIN_ANALYSIS_SECONDS
) -> tuple[npt.NDArray[np.float64], int]:
    """Decode an audio file into a mono float64 signal ready for analysis.

    Args:
        file_path:    Path to the audio file.
        max_duration: Cap on the decoded length (seconds), so slow tools
                      analyse a bounded window of each track. A positive
                      value truncates; ``0`` disables the cap.
        min_seconds:  Minimum usable audio duration. Shorter signals raise
                      AudioAnalysisError via ``check_analysable``.

    Returns:
        Two-tuple ``(y, sr)`` where *y* is a mono float64 array in the
        range [-1, 1] and *sr* is the native sample rate in Hz.

    Raises:
        AudioCodecError:   The file cannot be decoded (unsupported codec or
                           corrupted container).
        AudioAnalysisError: The decoded signal is shorter than *min_seconds*
                           or carries no audible energy.
    """
    try:
        y_f32, sample_rate = librosa_load_with_fallback(
            file_path, duration=max_duration, mono=True, sr=None
        )
    except AudioCodecError as exc:
        log_handled_failure(
            logger,
            "[%s] failed to decode '%s': %s",
            type(exc).__name__,
            file_path,
            exc.message,
            exc=exc.__cause__ or exc,
        )
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": file_path, "operation": "load_analysis_audio"}
        )
        error = (
            _missing_file_error(file_path)
            if not os.path.isfile(file_path)
            else decode_error(file_path, original=exc)
        )
        log_handled_failure(
            logger,
            "[%s] failed to decode '%s': %s",
            type(mapped).__name__,
            file_path,
            error.message,
            exc=exc,
        )
        raise error from exc

    sr = int(sample_rate)
    y: npt.NDArray[np.float64] = y_f32.astype(np.float64)
    check_analysable(y, sr, min_seconds=min_seconds)
    return y, sr


def check_analysable(
    y: npt.NDArray[np.float64], sr: int, *, min_seconds: float = MIN_ANALYSIS_SECONDS
) -> None:
    """Raise if the signal cannot yield a tempo, key or mood.

    This is the one guard every analysis tool must call after decoding.  It
    composes the duration check with the silence check so a decode path cannot
    adopt half of it: the duration guard alone let a blip be tagged with a
    fabricated BPM, and silence alone still reaches beat tracking, chroma
    correlation and mood heuristics as a flat spectrum — each of which returns
    a confident-looking value (a clamp-floor BPM, a key, a mood with
    confidence) that the tool then writes to the file.

    Args:
        y:           Audio signal (mono float64).
        sr:          Sample rate in Hz.
        min_seconds: Minimum acceptable duration.

    Raises:
        AudioAnalysisError: The signal is shorter than *min_seconds*, the
            sample rate is non-positive, or its global RMS is below
            ``SILENCE_RMS_THRESHOLD``.
    """
    check_min_duration(y, sr, min_seconds=min_seconds)
    check_not_silent(y)


def check_not_silent(y: npt.NDArray[np.float64]) -> None:
    """Raise if the signal is effectively silent.

    Args:
        y: Audio signal (mono float64).

    Raises:
        AudioAnalysisError: If the global RMS is below
            ``SILENCE_RMS_THRESHOLD`` (~ -60 dBFS).
    """
    if not is_effectively_silent(y):
        return
    level = rms_energy_db(y)
    raise AudioAnalysisError(
        f"Audio is effectively silent ({level:.0f} dBFS); nothing to analyse.",
        context={
            "rms_dbfs": level,
            "threshold_dbfs": 20.0 * float(np.log10(SILENCE_RMS_THRESHOLD)),
        },
    )


def check_min_duration(
    y: npt.NDArray[np.float64], sr: int, *, min_seconds: float = MIN_ANALYSIS_SECONDS
) -> None:
    """Raise if the signal is too short for meaningful analysis.

    Args:
        y:           Audio signal (mono float64).
        sr:          Sample rate in Hz.
        min_seconds: Minimum acceptable duration.

    Raises:
        AudioAnalysisError: If ``len(y) / sr < min_seconds``, or if the decoder
            reported a non-positive sample rate (a corrupt container can decode
            to an empty signal with ``sr == 0``).
    """
    if sr <= 0 or len(y) / sr < min_seconds:
        # A corrupt container can yield an empty signal with sr == 0, so the
        # duration is only computable once the rate is known to be positive.
        duration = len(y) / sr if sr > 0 else 0.0
        raise AudioAnalysisError(
            f"Audio is too short to analyse ({duration:.2f}s).",
            context={"min_seconds": min_seconds},
        )


def rms_energy_db(y: npt.NDArray[np.float64]) -> float:
    """Return the root-mean-square energy of a signal in dBFS.

    Args:
        y: Audio signal (mono float64).

    Returns:
        RMS level relative to full scale, e.g. ``-23.4``. Pure digital
        silence returns approximately ``-240`` (the epsilon floor).
    """
    if len(y) == 0:
        return -240.0
    rms: float = float(np.sqrt(np.mean(np.square(y), dtype=np.float64)))
    if rms <= 0.0:
        return -240.0
    return 20.0 * float(np.log10(rms))


def is_effectively_silent(y: npt.NDArray[np.float64]) -> bool:
    """Return True when the signal carries no perceptible energy.

    The check is against the global RMS level (~ -60 dBFS), not per-window
    energy, so it only rejects genuinely empty audio rather than sparse
    material with loud transients.

    Args:
        y: Audio signal (mono float64).

    Returns:
        True for a near-silent signal; False otherwise.
    """
    threshold_db: float = 20.0 * float(np.log10(SILENCE_RMS_THRESHOLD))
    return rms_energy_db(y) < threshold_db
