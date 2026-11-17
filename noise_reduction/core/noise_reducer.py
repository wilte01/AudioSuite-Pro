"""
core/noise_reducer.py
DSP engine for hum removal and broadband noise reduction.

Hum removal
-----------
The stage measures the file first (:func:`detect_hum`): it decides whether the
mains hum is 50 or 60 Hz and which of its partials stand above the local floor,
and only those are notched, each with a second-order IIR notch designed by
``scipy.signal.iirnotch``.  The cascade is applied in second-order-sections form
via ``scipy.signal.sosfilt``: every notch is one biquad section, and the SOS
layout keeps a low-frequency, high-Q notch well conditioned.  A manual 50/60
choice remains as an override and notches the fixed cascade instead.

Broadband noise reduction
-------------------------
Two engines, selected by ``NoiseReductionParams.broadband_engine``:

* ``spectral`` - STFT-based gating.  The user designates a short silent region
  as the noise profile.  Its mean magnitude spectrum becomes the gate
  threshold: frequency bins whose energy falls below the noise floor (plus a
  configurable headroom) are zeroed, suppressing stationary hiss and broadband
  noise while preserving tonal content above the noise floor.
* ``neural`` - RNNoise, the speech-trained model
  :mod:`noise_reduction.core.rnnoise_engine` runs
  program wrapped, reached through :func:`neural_gate`.  It needs no profile
  and adapts frame by frame, but it writes 16-bit audio and attenuates tonal
  content, so a source wider than that is refused unless the run accepts it
  (:func:`check_neural_bit_depth`).

Both halves are independent and can be applied individually or in sequence
(hum removal first, then whichever broadband engine is selected).

Changed in 2.8.0: the hum cascade is applied as the second-order sections this
docstring always described - ``remove_hum`` used to chain ``lfilter`` calls on
``(b, a)`` pairs while claiming SOS, and ``sosfilt`` now does what the module
says while giving the conditioning its high-Q notches need.  The broadband half
can run RNNoise as well as the STFT
gate.  The model lives in the optional ``ml`` extra and is imported only by the
calls that use it, so a base install keeps working;
``neural_dependency_reason`` lets a run ask before the batch whether the engine
it selected can start, and the neural engine's 16-bit output is a rule the stage
states rather than a re-encode nobody notices.

Changed in 2.1.6: the bare ``np.ndarray`` annotations are parameterised. numpy
1.26.4's stubs - what this project's lock installs below 3.12 - leave
``ndarray`` generic with no defaults, so ``--strict`` rejects a bare ``ndarray``
on the floor leg while numpy 2.5.4's stubs accepted it (R-15,
PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import logging
import math

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment
from scipy.signal import iirnotch, istft, sosfilt, stft, welch

from audio_suite_shared.audio_conversion import (
    clip_to_range,
    log_clip_event,
    numpy_to_segment,
    segment_to_numpy,
)
from audio_suite_shared.exceptions import AudioConfigurationError

from .models import (
    BROADBAND_ENGINES,
    NEURAL_OUTPUT_BITS,
    HumLine,
    HumProfile,
    NoiseAnalysis,
    NoiseReductionParams,
    NoiseReductionResult,
    NoiseWindow,
)

logger = logging.getLogger(__name__)

# ── Hum removal constants ────────────────────────────────────────────────────

_SUPPORTED_HUM_FREQUENCIES: frozenset[int] = frozenset({50, 60})
_MIN_HARMONICS: int = 1
_MAX_HARMONICS: int = 20
_MIN_QUALITY: float = 1.0
_MAX_QUALITY: float = 100.0

# Minimum energy attenuation (dB) for the hum stage to be considered a real
# modification.  A pure IIR notch passes non-hum content essentially unchanged
# (energy drift < 0.1 dB), so this threshold cleanly separates real hum
# removal (typically 8-14 dB) from benign floating-point drift on clean audio.
_MIN_ATTENUATION_DB: float = 3.0

# ── Hum detection constants ──────────────────────────────────────────────────
#: How much of the file the detector measures.  Mains hum is stationary, so 30 s
#: is plenty and keeps a two-hour concert from costing a full-file spectrum.
_HUM_ANALYSIS_SECONDS: float = 30.0
#: How far a partial must stand above the median of its neighbourhood to count
#: as hum.  A notch that removes nothing is not worth its phase shift, and 6 dB
#: still catches a hum that sits only slightly above the bed.
_HUM_MIN_PROMINENCE_DB: float = 6.0
#: Half-width of the band a partial's peak is searched in.  Mains hum drifts by
#: a few hundredths of a hertz; 2 Hz covers it without reaching the next one.
_HUM_PEAK_HALF_WIDTH_HZ: float = 2.0
#: Half-width of the neighbourhood whose median is the local floor, and the
#: dead band excluded so a neighbouring harmonic does not raise its own floor.
_HUM_FLOOR_HALF_WIDTH_HZ: float = 25.0
_HUM_FLOOR_DEAD_BAND_HZ: float = 3.0
#: A partial must also carry real energy, not just top a floor that is itself
#: numerical noise: a pure tone's leakage bins are billions of times above the
#: near-silent band around them and would otherwise read as hum.  The peak must
#: therefore be within 40 dB of the file's mean bin power.
_HUM_MIN_RELATIVE_POWER: float = 1e-4

# ── Spectral gating constants ────────────────────────────────────────────────

_DEFAULT_N_FFT: int = 2048
_DEFAULT_HOP_LENGTH: int = 512
_MIN_NOISE_REGION_MS: int = 100

# ── Noise-profile detection constants ────────────────────────────────────────
#: The window the detector reports, and the shortest it will accept.
_PROFILE_WINDOW_MS: int = 400
_PROFILE_MIN_WINDOW_MS: int = 300
#: The analysis hop: one frame per 100 ms, so a window is a whole number of
#: frames and its RMS is a power average of them.
_PROFILE_HOP_MS: int = 100
#: A window may only become the profile if it sits within this much of the
#: file's quietest: anything louder is content, not the floor.  Wide enough to
#: admit the hiss beside a musical rest, narrow enough to exclude the music.
_PROFILE_CANDIDATE_RANGE_DB: float = 12.0
#: How many of those quasi-quiet windows are trialled.  Each trial is one gate
#: over one 400 ms stretch, and a window below the shortlist is tonal enough to
#: lose on flatness anyway.
_PROFILE_CANDIDATES: int = 12
#: The trial is a guard, not a ranking: a candidate whose profile would remove
#: more than this from the file's loudest stretch is describing that content,
#: not a floor, and is dropped.  Measured on a music/rest/hiss file: a window of
#: the music removes 22.9 dB there and is dropped, while the quiet windows - a
#: musical rest and hiss alike - remove 0.00 dB, so the guard passes both and
#: flatness decides.  A window 10 dB under a noise bed removes 1.0-2.2 dB.
_PROFILE_TRIAL_MAX_DB: float = 1.0


# ── Internal helpers ─────────────────────────────────────────────────────────


def _rms_db(audio_f64: npt.NDArray[np.float64]) -> float:
    """Compute RMS level in dBFS from a float64 array (any shape)."""
    rms = float(np.sqrt(np.mean(audio_f64.astype(np.float64) ** 2)))
    if rms < 1e-12:
        return -120.0
    return 20.0 * math.log10(rms)


def _build_notch_sections(
    frequencies_hz: list[float],
    quality: float,
    sample_rate: int,
) -> npt.NDArray[np.float64]:
    """Design notches at *frequencies_hz* as a second-order-sections matrix.

    ``iirnotch`` returns one biquad per frequency as ``(b, a)`` with ``a[0] ==
    1``, so each becomes one SOS row ``[b0, b1, b2, 1, a1, a2]`` in the order
    given.  The section form is what keeps a 60 Hz notch at Q=100 well
    conditioned at a 44.1 kHz rate: the equivalent high-order transfer-function
    coefficients cannot represent poles that sit a few 1e-5 inside the unit
    circle.  Frequencies at or above Nyquist are dropped, because ``iirnotch``
    has no normalised frequency of 1 to design at.

    Returns
    -------
    An ``(sections, 6)`` float64 array, empty when no frequency fits below
    Nyquist.
    """
    nyquist = sample_rate / 2
    sections: list[npt.NDArray[np.float64]] = []
    for freq in frequencies_hz:
        if not 0.0 < freq < nyquist:
            continue
        b, a = iirnotch(freq, quality, fs=sample_rate)
        sections.append(np.concatenate([b, a]))
    if not sections:
        return np.empty((0, 6), dtype=np.float64)
    return np.vstack(sections)


def _window_samples(index: int, span: int, hop: int, limit: int) -> tuple[int, int]:
    """Return the sample bounds of the *span*-frame window starting at *index*."""
    return index * hop, min((index + span) * hop, limit)


def _hum_band_psd(
    mono: npt.NDArray[np.float64], sample_rate: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Return the one-sided power density the detector measures hum from."""
    window = min(len(mono), 1 << 15)
    if window < 1024:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    freqs, psd = welch(mono, fs=sample_rate, nperseg=window, noverlap=window // 2)
    return np.asarray(freqs, dtype=np.float64), np.asarray(psd, dtype=np.float64)


def _prominence_at(
    freqs: npt.NDArray[np.float64],
    psd: npt.NDArray[np.float64],
    frequency_hz: float,
    noise_reference: float,
) -> float | None:
    """Return how far a partial at *frequency_hz* stands above its local floor.

    The floor is the median of the surrounding band with a dead band carved out
    around the partial itself, so a neighbouring harmonic (or the partial's own
    skirt) cannot set the reference it is measured against.  *noise_reference*
    is the file's mean bin power, and a peak below ``_HUM_MIN_RELATIVE_POWER``
    of it is leakage, not hum.  ``None`` means the partial is outside the
    measured range, the floor is silent, or the peak carries no real energy.
    """
    if freqs.size == 0 or frequency_hz <= 0.0 or frequency_hz >= freqs[-1]:
        return None
    peak_band = (freqs >= frequency_hz - _HUM_PEAK_HALF_WIDTH_HZ) & (
        freqs <= frequency_hz + _HUM_PEAK_HALF_WIDTH_HZ
    )
    if not np.any(peak_band):
        return None
    peak = float(np.max(psd[peak_band]))
    if peak <= 0.0 or peak < noise_reference * _HUM_MIN_RELATIVE_POWER:
        return None
    floor_band = (
        (freqs >= frequency_hz - _HUM_FLOOR_HALF_WIDTH_HZ)
        & (freqs <= frequency_hz + _HUM_FLOOR_HALF_WIDTH_HZ)
        & ~(
            (freqs >= frequency_hz - _HUM_FLOOR_DEAD_BAND_HZ)
            & (freqs <= frequency_hz + _HUM_FLOOR_DEAD_BAND_HZ)
        )
    )
    floor = float(np.median(psd[floor_band])) if np.any(floor_band) else 0.0
    if peak <= 0.0 or floor <= 0.0:
        return None
    return 10.0 * math.log10(peak / floor)


def _spectrum_profile(
    samples: npt.NDArray[np.float64], fs: int
) -> npt.NDArray[np.float64]:
    """Return the mean magnitude spectrum of *samples*, shaped ``(bins, 1)``."""
    _, _, transform = stft(
        samples,
        fs=fs,
        nperseg=_DEFAULT_N_FFT,
        noverlap=_DEFAULT_N_FFT - _DEFAULT_HOP_LENGTH,
    )
    profile: npt.NDArray[np.float64] = np.mean(np.abs(transform), axis=1, keepdims=True)
    return profile


def _gate_channel(
    channel: npt.NDArray[np.float64],
    gate: npt.NDArray[np.float64],
    fs: int,
    n_fft: int = _DEFAULT_N_FFT,
    hop_length: int = _DEFAULT_HOP_LENGTH,
) -> tuple[npt.NDArray[np.float64], float]:
    """Zero the bins of *channel* below *gate*, returning it and the share cut.

    *gate* is a magnitude threshold per bin (``(bins, 1)``), so the same gate can
    be applied to any amount of audio: a run applies it to a whole channel, the
    profile detector to one window of the file.
    """
    orig_len = len(channel)

    _, _, Zxx = stft(channel, fs=fs, nperseg=n_fft, noverlap=n_fft - hop_length)
    mag = np.abs(Zxx)
    passing = mag >= gate
    gated_share = float(1.0 - np.mean(passing))

    cleaned_transform = np.where(passing, mag, 0.0) * np.exp(1j * np.angle(Zxx))
    _, cleaned = istft(
        cleaned_transform, fs=fs, nperseg=n_fft, noverlap=n_fft - hop_length
    )

    if len(cleaned) < orig_len:
        cleaned = np.pad(cleaned, (0, orig_len - len(cleaned)))
    elif len(cleaned) > orig_len:
        cleaned = cleaned[:orig_len]

    return np.asarray(cleaned, dtype=np.float64), gated_share


def _spectral_gate_channel(
    channel: npt.NDArray[np.float64],
    fs: int,
    noise_start_ms: int,
    noise_end_ms: int,
    gate_threshold_db: float,
    n_fft: int,
    hop_length: int,
) -> tuple[npt.NDArray[np.float64], float]:
    """Apply spectral gating to a single-channel float64 signal.

    The profile is the mean magnitude of the region's STFT frames, and the gate
    is that profile raised by the threshold; *channel* is then filtered by
    :func:`_gate_channel`.

    Parameters
    ----------
    channel : 1-D float64 array.
    fs : Sample rate in Hz.
    noise_start_ms, noise_end_ms : Bounds of the noise profile region.
    gate_threshold_db : Headroom in dB above the noise floor.
    n_fft : STFT window length.
    hop_length : STFT hop length.

    Returns
    -------
    The cleaned 1-D float64 array (same length as input), and the share of the
    time-frequency bins the gate suppressed (0-1).
    """
    _, times, Zxx = stft(channel, fs=fs, nperseg=n_fft, noverlap=n_fft - hop_length)
    mag = np.abs(Zxx)

    noise_mask = (times >= noise_start_ms / 1000.0) & (times <= noise_end_ms / 1000.0)
    if not np.any(noise_mask):
        noise_mask = times <= noise_end_ms / 1000.0

    profile: npt.NDArray[np.float64] = np.mean(
        mag[:, noise_mask], axis=1, keepdims=True
    )
    gate = profile * (10.0 ** (gate_threshold_db / 20.0))
    return _gate_channel(channel, gate, fs, n_fft, hop_length)


# ── Public API ────────────────────────────────────────────────────────────────


def remove_hum(
    audio: AudioSegment,
    fundamental_hz: int = 60,
    harmonics: int = 8,
    quality: float = 30.0,
) -> NoiseReductionResult:
    """Remove mains hum and its harmonics via cascaded IIR notch filters.

    Parameters
    ----------
    audio : AudioSegment
        Input audio (mono or multi-channel, any supported bit depth).
    fundamental_hz : int
        Mains frequency: 50 or 60 Hz.
    harmonics : int
        Number of harmonics to filter (1-20).
    quality : float
        Q factor for each notch filter (1.0-100.0).  Higher values produce
        narrower notches that preserve more adjacent content.

    Returns
    -------
    NoiseReductionResult
        (processed audio, energy before dB, energy after dB, was_modified).

    Raises
    ------
    AudioConfigurationError
        If parameters are outside acceptable ranges.
    """
    if fundamental_hz not in _SUPPORTED_HUM_FREQUENCIES:
        raise AudioConfigurationError(
            f"hum_frequency must be one of {sorted(_SUPPORTED_HUM_FREQUENCIES)}, "
            f"got {fundamental_hz}"
        )
    if not (_MIN_HARMONICS <= harmonics <= _MAX_HARMONICS):
        raise AudioConfigurationError(
            f"hum_harmonics must be {_MIN_HARMONICS}-{_MAX_HARMONICS}, got {harmonics}"
        )
    return remove_hum_lines(
        audio, fundamental_hz, tuple(range(1, harmonics + 1)), quality
    )


def detect_hum(
    audio: AudioSegment,
    harmonics: int = 8,
    min_prominence_db: float = _HUM_MIN_PROMINENCE_DB,
) -> HumProfile | None:
    """Measure which mains frequency this file carries, and how strongly.

    The file decides, not the region it was recorded in: 50 Hz and 60 Hz are
    only 10 Hz apart, and choosing the wrong one misses every partial while
    notching eight frequencies out of the music.  Each candidate's partials are
    scored by how far each stands above the median of its own neighbourhood,
    so the answer does not depend on how loud the file is; the fundamental
    counts first when the two candidates share a partial (their lowest common
    harmonic is 300 Hz).

    Only the first 30 seconds are measured - mains hum is stationary - and a
    silent or very short file measures nothing rather than guessing.

    Args:
        audio: The decoded source.
        harmonics: The highest order the detector reports (1-20).
        min_prominence_db: How far a partial must stand above the local floor.

    Returns:
        The measured profile, or ``None`` when no partial clears the floor.

    Raises:
        AudioConfigurationError: *harmonics* is outside 1-20.
    """
    if not (_MIN_HARMONICS <= harmonics <= _MAX_HARMONICS):
        raise AudioConfigurationError(
            f"hum_harmonics must be {_MIN_HARMONICS}-{_MAX_HARMONICS}, got {harmonics}"
        )

    sample_rate = audio.frame_rate
    samples_f32, _rate = segment_to_numpy(audio)
    if samples_f32.size == 0:
        return None
    limit = max(int(sample_rate * _HUM_ANALYSIS_SECONDS), 1024)
    window = samples_f32[:, :limit].astype(np.float64)
    mono = np.mean(window, axis=0)

    freqs, psd = _hum_band_psd(mono, sample_rate)
    if freqs.size == 0:
        return None
    noise_reference = float(np.mean(psd))
    if noise_reference <= 0.0:
        return None

    best: tuple[tuple[int, int, float], HumProfile] | None = None
    for candidate in sorted(_SUPPORTED_HUM_FREQUENCIES):
        lines: list[HumLine] = []
        for order in range(1, harmonics + 1):
            frequency = float(candidate * order)
            prominence = _prominence_at(freqs, psd, frequency, noise_reference)
            if prominence is not None and prominence >= min_prominence_db:
                lines.append(HumLine(order, frequency, prominence))
        if not lines:
            continue
        # Changed in 2.8.0: mains hum starts at the mains frequency.  A spectrum
        # whose lowest partial is the 6th harmonic is content, not hum - white
        # noise clears 6 dB at a high partial regularly - and notching 360 Hz
        # because 60 Hz was noisy would remove music.  An octave counts because
        # a recording high-passed above the fundamental keeps order 2.
        if min(line.order for line in lines) > 2:
            continue
        profile = HumProfile(fundamental_hz=candidate, lines=tuple(lines))
        score = (1 if 1 in profile.orders else 0, len(lines), profile.level_db)
        if best is None or score > best[0]:
            best = (score, profile)
    return None if best is None else best[1]


def remove_hum_lines(
    audio: AudioSegment,
    fundamental_hz: int,
    orders: tuple[int, ...],
    quality: float = 30.0,
    hum_profile: HumProfile | None = None,
) -> NoiseReductionResult:
    """Notch exactly *orders* of *fundamental_hz*, nothing else.

    This is the one hum cascade: the manual path passes every order up to the
    configured harmonic count, the auto path passes only the orders the profile
    measured, and both run the same SOS code.

    Args:
        audio: Input audio.
        fundamental_hz: Mains frequency, 50 or 60.
        orders: The harmonic orders to notch, ascending.
        quality: Q factor for each notch (1.0-100.0).
        hum_profile: The measurement this cascade came from, when there was one;
            carried on the result so the stage can report it.

    Returns:
        ``(audio, energy_before_db, energy_after_db, was_modified, hum_profile)``.

    Raises:
        AudioConfigurationError: The frequency, quality or order set is invalid.
    """
    if fundamental_hz not in _SUPPORTED_HUM_FREQUENCIES:
        raise AudioConfigurationError(
            f"hum_frequency must be one of {sorted(_SUPPORTED_HUM_FREQUENCIES)}, "
            f"got {fundamental_hz}"
        )
    if not (_MIN_QUALITY <= quality <= _MAX_QUALITY):
        raise AudioConfigurationError(
            f"hum_quality must be {_MIN_QUALITY}-{_MAX_QUALITY}, got {quality}"
        )

    sample_rate = audio.frame_rate
    num_channels = audio.channels

    samples_f32, _sample_rate = segment_to_numpy(audio)  # (channels, frames) float32
    samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64 for scipy

    energy_before = _rms_db(samples)

    sos = _build_notch_sections(
        [fundamental_hz * order for order in orders], quality, sample_rate
    )
    if sos.shape[0] == 0:
        return NoiseReductionResult(
            audio, energy_before, energy_before, False, hum_profile
        )

    for ch in range(num_channels):
        samples[:, ch] = sosfilt(sos, samples[:, ch])

    energy_after = _rms_db(samples)

    if energy_before - energy_after < _MIN_ATTENUATION_DB:
        return NoiseReductionResult(
            audio, energy_before, energy_before, False, hum_profile
        )

    clipped = clip_to_range(samples.T.astype(np.float32))  # back to (channels, frames)
    log_clip_event(clipped, "noise_reduction", logger)
    new_audio = numpy_to_segment(
        clipped,
        sample_rate,
        sample_width=audio.sample_width,
        num_channels=audio.channels,
    )
    return NoiseReductionResult(
        new_audio, energy_before, energy_after, True, hum_profile
    )


def detect_noise_profile(
    audio: AudioSegment, gate_threshold_db: float = 3.0
) -> NoiseWindow | None:
    """Pick the window whose profile is the file's noise floor, not its music.

    The first 500 ms of a track is an intro more often than it is noise, and a
    profile taken there makes the gate either do nothing (the profile is hot) or
    eat the music (it is not noise at all).  So the file is cut into 100 ms
    frames, their power and spectral flatness measured, and every window within
    :data:`_PROFILE_CANDIDATE_RANGE_DB` of the quietest considered.  Each is
    trialled - its profile gates the file's *loudest* stretch - but as a
    **guard**, not a ranking: a candidate that would remove more than
    :data:`_PROFILE_TRIAL_MAX_DB` there is close enough in level to the content
    to be describing it and is dropped, while the candidates that pass are
    ranked by flatness, then quietness.  That split is measured, not assumed:
    on a file of music, a musical rest and hiss, a window of the music removes
    22.9 dB from the loudest stretch and is rejected, while the rest and the
    hiss each remove 0.00 dB - so the trial cannot separate those two, and
    flatness is what does (the hiss reads 0.85 against a tonal rest far below).
    Quiet alone is not enough either, because a silent stretch gives the gate
    nothing to subtract.  When
    even the flattest candidate is content-derived, the ceiling cannot be met
    and the flattest still wins, with its trial reading reported so the run is
    auditable.

    Args:
        audio: The decoded source.
        gate_threshold_db: The run's headroom, so the trial asks the question
            the real gate will.

    Returns:
        The chosen window, or ``None`` when the file is too short to measure.
        The caller then keeps the region it was configured with.
    """
    hop = max(int(audio.frame_rate * _PROFILE_HOP_MS / 1000.0), 1)
    samples, _ = segment_to_numpy(audio)
    mono = samples.mean(axis=0, dtype=np.float64)
    total_ms = int(round(len(audio)))
    frames = mono.size // hop
    if total_ms < _PROFILE_MIN_WINDOW_MS or frames < 2:
        return None
    window_ms = min(_PROFILE_WINDOW_MS, total_ms)

    frame_matrix = mono[: frames * hop].reshape(frames, hop)
    power = np.mean(np.square(frame_matrix), axis=1)
    taper = np.hanning(hop)
    spectrum = np.abs(np.fft.rfft(frame_matrix * taper, axis=1)) + 1e-12
    flatness = np.exp(np.mean(np.log(spectrum), axis=1)) / np.mean(spectrum, axis=1)

    # Cumulative sums score every window in one pass: a window's mean power and
    # mean flatness are two subtracted prefixes, not a fresh FFT per start.
    span = min(int(round(window_ms / _PROFILE_HOP_MS)), frames)
    starts = np.arange(frames - span + 1)
    power_prefix = np.concatenate(([0.0], np.cumsum(power)))
    flat_prefix = np.concatenate(([0.0], np.cumsum(flatness)))
    window_flat = (flat_prefix[starts + span] - flat_prefix[starts]) / span
    window_db = 10.0 * np.log10(
        np.maximum((power_prefix[starts + span] - power_prefix[starts]) / span, 1e-12)
    )

    sample_rate = audio.frame_rate
    quietest = float(np.min(window_db))
    quasi_quiet = np.flatnonzero(window_db <= quietest + _PROFILE_CANDIDATE_RANGE_DB)
    # The flattest few are trialled; a window below that shortlist is tonal
    # enough to lose on flatness, so trialling it would buy nothing.
    shortlist = quasi_quiet[
        np.argsort(window_flat[quasi_quiet])[::-1][:_PROFILE_CANDIDATES]
    ]

    loudest_start, loudest_stop = _window_samples(
        int(np.argmax(window_db)), span, hop, mono.size
    )
    reference = mono[loudest_start:loudest_stop]
    trial: dict[int, float] = {}
    for candidate in shortlist:
        start, stop = _window_samples(int(candidate), span, hop, mono.size)
        profile = _spectrum_profile(mono[start:stop], sample_rate)
        gate = profile * (10.0 ** (gate_threshold_db / 20.0))
        cleaned, _ = _gate_channel(reference, gate, sample_rate)
        trial[int(candidate)] = max(_rms_db(reference) - _rms_db(cleaned), 0.0)

    # Guard first, then flatness: a candidate that would cut the loudest
    # stretch is describing that content, and a run with no floor anywhere
    # keeps the flattest of a bad set rather than raising.
    survivors = [
        index for index, removed in trial.items() if removed <= _PROFILE_TRIAL_MAX_DB
    ]
    best = min(
        survivors or list(trial),
        key=lambda index: (-float(window_flat[index]), float(window_db[index])),
    )
    return NoiseWindow(
        start_ms=best * _PROFILE_HOP_MS,
        end_ms=min((best + span) * _PROFILE_HOP_MS, total_ms),
        rms_dbfs=float(window_db[best]),
        flatness=float(window_flat[best]),
        trial_db=trial[best],
    )


def analyse_noise(
    audio: AudioSegment, *, hum_harmonics: int = 8, gate_threshold_db: float = 3.0
) -> NoiseAnalysis:
    """Measure a file the way the batch would, without processing it.

    This is the panel's Analyse action: the same ``detect_hum`` (first 30 s)
    and ``detect_noise_profile`` (whole file) the run itself calls, so the
    numbers reported are the ones a run would act on.  It decodes nothing to
    disk, writes nothing and never mutates *audio*.

    Args:
        audio: The decoded source to measure.
        hum_harmonics: Highest harmonic the hum detector reports (the
            stage's ``Hum Harmonics`` setting).
        gate_threshold_db: The gate headroom the profile trial uses (the
            stage's ``Gate Threshold`` setting).

    Returns:
        The hum finding, the recommended profile window and the floor either
        implies.
    """
    samples_f32, _sample_rate = segment_to_numpy(audio)
    file_rms = float(_rms_db(samples_f32.T.astype(np.float64)))
    return NoiseAnalysis(
        hum=detect_hum(audio, harmonics=hum_harmonics),
        window=detect_noise_profile(audio, gate_threshold_db),
        file_rms_dbfs=file_rms,
        duration_s=len(audio) / 1000.0,
    )


def spectral_gate(
    audio: AudioSegment,
    noise_start_ms: int = 0,
    noise_end_ms: int = 500,
    gate_threshold_db: float = 3.0,
    n_fft: int = _DEFAULT_N_FFT,
    hop_length: int = _DEFAULT_HOP_LENGTH,
) -> NoiseReductionResult:
    """Reduce broadband noise via STFT-based spectral gating.

    Parameters
    ----------
    audio : AudioSegment
        Input audio.
    noise_start_ms : int
        Start of the noise profile region in milliseconds.
    noise_end_ms : int
        End of the noise profile region in milliseconds.
    gate_threshold_db : float
        Headroom in dB above the measured noise floor.  Bins below this
        threshold are zeroed.
    n_fft : int
        STFT window length.
    hop_length : int
        STFT hop length.

    Returns
    -------
    NoiseReductionResult

    Raises
    ------
    AudioConfigurationError
        If the noise region is too short or parameters are invalid.
    """
    if noise_end_ms - noise_start_ms < _MIN_NOISE_REGION_MS:
        raise AudioConfigurationError(
            f"Noise profile region must be at least {_MIN_NOISE_REGION_MS} ms, "
            f"got {noise_end_ms - noise_start_ms} ms"
        )
    if noise_start_ms < 0:
        raise AudioConfigurationError(
            f"noise_start_ms must be >= 0, got {noise_start_ms}"
        )
    if noise_end_ms <= noise_start_ms:
        raise AudioConfigurationError(
            f"noise_end_ms ({noise_end_ms}) must be > noise_start_ms ({noise_start_ms})"
        )

    sample_rate = audio.frame_rate
    num_channels = audio.channels

    samples_f32, _sample_rate = segment_to_numpy(audio)  # (channels, frames) float32
    samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64 for scipy

    energy_before = _rms_db(samples)

    modified = False
    gated_shares: list[float] = []
    for ch in range(num_channels):
        cleaned, gated_share = _spectral_gate_channel(
            samples[:, ch],
            sample_rate,
            noise_start_ms,
            noise_end_ms,
            gate_threshold_db,
            n_fft,
            hop_length,
        )
        gated_shares.append(gated_share)
        if not np.allclose(cleaned, samples[:, ch], atol=1e-6):
            modified = True
            samples[:, ch] = cleaned

    gated_share_mean = float(np.mean(gated_shares)) if gated_shares else 0.0
    if not modified:
        return NoiseReductionResult(
            audio,
            energy_before,
            energy_before,
            False,
            gate_attenuation_db=0.0,
            gated_bin_share=gated_share_mean,
        )

    energy_after = _rms_db(samples)

    clipped = clip_to_range(samples.T.astype(np.float32))  # back to (channels, frames)
    log_clip_event(clipped, "noise_reduction", logger)
    new_audio = numpy_to_segment(
        clipped,
        sample_rate,
        sample_width=audio.sample_width,
        num_channels=audio.channels,
    )
    return NoiseReductionResult(
        new_audio,
        energy_before,
        energy_after,
        True,
        gate_attenuation_db=energy_before - energy_after,
        gated_bin_share=gated_share_mean,
    )


def reduce_noise(
    audio: AudioSegment,
    params: NoiseReductionParams,
) -> NoiseReductionResult:
    """Apply noise reduction according to the given parameters.

    Both hum removal and spectral gating can be enabled independently.
    When both are active, hum removal runs first.

    Parameters
    ----------
    audio : AudioSegment
        Input audio.
    params : NoiseReductionParams
        Processing parameters.

    Returns
    -------
    NoiseReductionResult
    """
    # ``params.dry_run`` is deliberately NOT consulted here.  The DSP always
    # measures and reports what it found; suppressing the write is the shared
    # in-place workflow's job (it passes ``is_dry_run`` separately and skips
    # the export), so a dry run can report ``was_modified=True`` honestly
    # instead of having to claim the file was clean.  This matches
    # ``pop_click_remover``'s declicker.
    current = audio
    any_modified = False
    energy_before_total = 0.0
    energy_after_total = 0.0
    hum_profile: HumProfile | None = None
    noise_window: NoiseWindow | None = None
    gate_attenuation_db: float | None = None
    gated_bin_share: float | None = None

    if params.reduce_hum:
        # Changed in 2.8.0: the file says whether it carries 50 or 60 Hz and
        # which of its partials are real, so only those are notched.  A manual
        # choice still notches the fixed cascade on request.
        hum_result: NoiseReductionResult | None = None
        if params.hum_auto:
            hum_profile = detect_hum(current, harmonics=params.hum_harmonics)
            if hum_profile is not None:
                hum_result = remove_hum_lines(
                    current,
                    hum_profile.fundamental_hz,
                    hum_profile.orders,
                    params.hum_quality,
                    hum_profile,
                )
        else:
            hum_result = remove_hum(
                current,
                fundamental_hz=params.hum_frequency,
                harmonics=params.hum_harmonics,
                quality=params.hum_quality,
            )
        if hum_result is not None:
            if energy_before_total == 0.0:
                energy_before_total = hum_result.energy_before_db
            energy_after_total = hum_result.energy_after_db
            if hum_result.was_modified:
                current = hum_result.audio
                any_modified = True

    if params.reduce_broadband:
        if params.broadband_engine not in BROADBAND_ENGINES:
            raise AudioConfigurationError(
                f"broadband_engine must be one of {list(BROADBAND_ENGINES)}, "
                f"got {params.broadband_engine!r}"
            )
        if params.neural_selected():
            result = neural_gate(current, params.neural_amount)
        else:
            # Changed in 2.8.0: the profile comes from the quietest, flattest
            # stretch of this file unless the run names its own region.
            if params.profile_auto:
                noise_window = detect_noise_profile(current, params.gate_threshold_db)
            if noise_window is not None:
                start_ms = noise_window.start_ms
                end_ms = noise_window.end_ms
            else:
                start_ms = params.noise_start_ms
                end_ms = params.noise_end_ms
            result = spectral_gate(
                current,
                noise_start_ms=start_ms,
                noise_end_ms=end_ms,
                gate_threshold_db=params.gate_threshold_db,
            )
        if energy_before_total == 0.0:
            energy_before_total = result.energy_before_db
        energy_after_total = result.energy_after_db
        # The gate measured itself where only the gate ran; hum removal is in the
        # stage totals but not in these two numbers.
        gate_attenuation_db = result.gate_attenuation_db
        gated_bin_share = result.gated_bin_share
        if result.was_modified:
            current = result.audio
            any_modified = True

    if not any_modified:
        samples_f32, _sample_rate = segment_to_numpy(audio)
        energy = _rms_db(samples_f32.T.astype(np.float64))
        return NoiseReductionResult(
            audio,
            energy,
            energy,
            False,
            hum_profile,
            noise_window,
            gate_attenuation_db,
            gated_bin_share,
        )

    return NoiseReductionResult(
        current,
        energy_before_total,
        energy_after_total,
        True,
        hum_profile,
        noise_window,
        gate_attenuation_db,
        gated_bin_share,
    )


def neural_gate(audio: AudioSegment, amount: float) -> NoiseReductionResult:
    """Reduce broadband noise with the RNNoise model.

    The model is part of the optional ``ml`` extra, so the import happens in
    this function rather than at module import: a base install can open REFINE,
    configure a neural run and read this module's message without the extra
    present.  The measurement and the 16-bit output are the model's own; this
    adapter only re-shapes its result for the noise stage.

    Args:
        audio: Input audio, at the source's rate and channel count.
        amount: Blend of the model's output with the source, 0-1.  1.0 is the
            model's own result.

    Returns:
        A :class:`NoiseReductionResult` whose audio keeps the source's rate,
        channel count and length, at 16-bit resolution.

    Raises:
        AudioMissingDependencyError: RNNoise is not installed.
        ValueError: *amount* is out of range.
    """
    from noise_reduction.core.rnnoise_engine import denoise_segment

    result = denoise_segment(audio, amount)
    return NoiseReductionResult(
        audio=result.audio,
        energy_before_db=result.rms_before_db,
        energy_after_db=result.rms_after_db,
        was_modified=result.was_modified,
    )


def neural_dependency_reason(params: NoiseReductionParams) -> str | None:
    """Return why the neural engine cannot run, or ``None`` when it can.

    A run-level question, meant to be asked before the batch: a missing model is
    not one file's fault, so a run refuses once with the install instruction
    instead of failing every file with the same error.  ``pyrnnoise`` is only
    imported when the neural engine is actually selected.

    Args:
        params: The run's noise parameters.

    Returns:
        The missing-dependency message, or ``None`` when the engine is unused or
        importable.
    """
    if not params.neural_selected():
        return None
    from noise_reduction.core.rnnoise_engine import missing_dependency_reason

    return missing_dependency_reason()


def _source_bits(audio: AudioSegment, file_path: str | None) -> int:
    """Return the source's bit depth for the refusal message.

    pydub widens a 24-bit source to 32-bit samples, so ``sample_width * 8``
    overstates it.  The file's own declaration comes from the shared reader
    REFINE's export uses to pin a lossless rewrite's depth; a file that cannot
    be probed (or a caller that passed no path) falls back to the decode.

    Args:
        audio: The decoded source.
        file_path: The file it came from, when known.

    Returns:
        The declared depth in bits, or the decoded sample width in bits.
    """
    if file_path is not None:
        from audio_suite_shared.audio_formats import source_bit_depth

        declared = source_bit_depth(file_path)
        if declared:
            return int(declared)
    return int(audio.sample_width) * 8


def check_neural_bit_depth(
    audio: AudioSegment,
    params: NoiseReductionParams,
    file_path: str | None = None,
) -> int | None:
    """Refuse a source wider than the neural engine's 16-bit output.

    REFINE's export preserves the source's bit depth, so a stage that cannot is
    a change nobody asked for: a 24-bit FLAC denoised by RNNoise carries 16 bits
    of resolution whatever the container says.  The rule is a refusal by
    default - a run that wants both has the spectral engine, which keeps the
    depth, or a 16-bit copy of the source.  ``allow_16bit_output`` is the
    explicit opt-in: it lets the run narrow the source, and the stage line then
    states the depth the written file carries.

    Args:
        audio: The decoded source.
        params: The run's noise parameters.
        file_path: The file being processed, named in the refusal when known.

    Returns:
        The source's declared depth when a wider source was let through by
        ``allow_16bit_output``, otherwise ``None``.

    Raises:
        AudioConfigurationError: The neural engine is selected, the source is
            wider than 16-bit and the opt-in is off.
    """
    if not params.neural_selected():
        return None
    if audio.sample_width <= 2:
        return None
    source_bits = _source_bits(audio, file_path)
    if params.allow_16bit_output:
        return source_bits
    where = f"{file_path}: " if file_path is not None else ""
    raise AudioConfigurationError(
        f"{where}the neural denoiser writes {NEURAL_OUTPUT_BITS}-bit audio and this "
        f"source is {source_bits}-bit. Use the spectral engine, which keeps the "
        "source's bit depth, or denoise a 16-bit copy."
    )
