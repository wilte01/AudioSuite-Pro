"""dsp_eq.py — Parametric EQ: one band model, one measured response, one render.

This module is the suite's only parametric-EQ implementation (F-S1 of
``PLAN_2026-11-03_2.7.0_feature_wave_3.md``). It is pure: no tkinter, no file
I/O and no module-level mutable state, so the Refinery stage, its CLI flags and
its GUI panel all render the same band list, and a test can measure the result
without a window.

The response curve is measured, not re-derived
----------------------------------------------
``response_curve`` feeds a unit impulse through the very Pedalboard the render
path uses and takes the FFT of the result, so the curve a user looks at *is*
the transfer function that gets applied. A hand-derived biquad formula would be
a second implementation that can drift from the render the first time a filter
is swapped; pedalboard 0.9.25 exposes no coefficients to share, and measuring
its own impulse response is the one route that cannot disagree with it. The
acceptance test measures rendered tones against the curve to 0.5 dB.

High-pass and low-pass carry no Q
---------------------------------
pedalboard 0.9.25 ships first-order ``HighpassFilter``/``LowpassFilter`` that
take ``cutoff_frequency_hz`` only (verified against the installed build), while
the shelf and peak filters take ``q``. A band therefore keeps its declared Q
for every kind, but :class:`EqBand` refuses a non-default Q on a kind the
renderer cannot apply rather than accepting it and silently ignoring it: a
control that does nothing is the fabricated-value class this suite bans.

Changed in 2.7.0: new module — the parametric EQ engine (F-S1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import AudioConfigValueError

#: The band shapes the renderer implements. Declared once, and ``EqBand``
#: validates against it, so the CLI, a saved preset and the GUI table cannot
#: name a filter that does not exist.
BandKind = Literal["lowshelf", "highshelf", "peaking", "highpass", "lowpass"]
EQ_BAND_KINDS: tuple[BandKind, ...] = get_args(BandKind)

#: A rack a person can reason about, and the plan's declared limit.
MAX_EQ_BANDS: int = 8

EQ_MIN_FREQ_HZ: float = 20.0
EQ_MAX_FREQ_HZ: float = 20_000.0
EQ_MAX_GAIN_DB: float = 24.0
EQ_MIN_Q: float = 0.1
EQ_MAX_Q: float = 18.0

#: The Q a band gets when the caller does not care. Also the only Q the
#: first-order high-pass and low-pass kinds can honour.
EQ_DEFAULT_Q: float = 0.707

#: Kinds whose pedalboard filter has no Q parameter at all (see the module
#: docstring). A band of one of these kinds must carry :data:`EQ_DEFAULT_Q`.
EQ_FIXED_Q_KINDS: tuple[BandKind, ...] = ("highpass", "lowpass")

#: The curve's default impulse length. 65,536 samples is 0.67 Hz per bin at
#: 44.1 kHz, so interpolating 1/3-octave points off it adds no measurable error
#: while staying far cheaper than a sweep.
CURVE_FFT_SIZE: int = 65_536


@dataclass(frozen=True)
class EqBand:
    """One filter in the parametric rack.

    Attributes:
        kind: Which shape to apply (see :data:`EQ_BAND_KINDS`).
        freq_hz: Corner or centre frequency in Hz.
        gain_db: Shelf/peak gain in dB. Ignored by the high-pass and low-pass
            kinds, which is asserted rather than assumed: their gain must be
            ``0.0``.
        q: Filter Q. The shelf and peak kinds use it; the first-order
            high-pass and low-pass kinds refuse anything but the default.
    """

    kind: BandKind
    freq_hz: float
    gain_db: float = 0.0
    q: float = EQ_DEFAULT_Q

    def __post_init__(self) -> None:
        """Refuse a band the renderer cannot apply as written.

        Raises:
            AudioConfigValueError: When the kind is unknown, a value is out of
                range, or a first-order kind is given a Q it cannot honour.
        """
        if self.kind not in EQ_BAND_KINDS:
            raise AudioConfigValueError(
                f"Unknown EQ band kind {self.kind!r}; expected one of "
                f"{list(EQ_BAND_KINDS)}",
                context={"field": "eq_band_kind", "value": self.kind},
            )
        if not EQ_MIN_FREQ_HZ <= self.freq_hz <= EQ_MAX_FREQ_HZ:
            raise AudioConfigValueError(
                f"EQ band frequency {self.freq_hz} Hz is outside "
                f"{EQ_MIN_FREQ_HZ:.0f}-{EQ_MAX_FREQ_HZ:.0f} Hz",
                context={"field": "eq_freq_hz", "value": self.freq_hz},
            )
        if not -EQ_MAX_GAIN_DB <= self.gain_db <= EQ_MAX_GAIN_DB:
            raise AudioConfigValueError(
                f"EQ band gain {self.gain_db} dB is outside +/-{EQ_MAX_GAIN_DB:.0f} dB",
                context={"field": "eq_gain_db", "value": self.gain_db},
            )
        if not EQ_MIN_Q <= self.q <= EQ_MAX_Q:
            raise AudioConfigValueError(
                f"EQ band Q {self.q} is outside {EQ_MIN_Q}-{EQ_MAX_Q}",
                context={"field": "eq_q", "value": self.q},
            )
        if self.kind in EQ_FIXED_Q_KINDS:
            if self.gain_db != 0.0:
                raise AudioConfigValueError(
                    f"A {self.kind} EQ band has no gain; got {self.gain_db} dB",
                    context={
                        "field": "eq_gain_db",
                        "value": self.gain_db,
                        "kind": self.kind,
                    },
                )
            if self.q != EQ_DEFAULT_Q:
                raise AudioConfigValueError(
                    f"A {self.kind} EQ band is first-order and carries no Q; "
                    f"got {self.q} (the installed filter accepts "
                    f"{EQ_DEFAULT_Q} only)",
                    context={
                        "field": "eq_q",
                        "value": self.q,
                        "kind": self.kind,
                    },
                )

    def describe(self) -> str:
        """Return the band as the CLI spells it: ``kind,freq,gain,q``.

        Returns:
            A comma-separated band string, e.g. ``"peaking,1000,3.0,1.0"``.
        """
        return f"{self.kind},{self.freq_hz:g},{self.gain_db:g},{self.q:g}"


@dataclass(frozen=True)
class EqSettings:
    """A whole parametric rack, plus its bypass.

    Attributes:
        bands: At most :data:`MAX_EQ_BANDS` filters, applied in order.
        bypass: When true the render returns its input untouched. A bypassed
            rack is not the same thing as an empty one: the bands survive a
            round-trip through a preset while the sound does not change.
    """

    bands: tuple[EqBand, ...] = ()
    bypass: bool = False

    def __post_init__(self) -> None:
        """Refuse a rack larger than the declared maximum.

        Raises:
            AudioConfigValueError: When more than :data:`MAX_EQ_BANDS` bands
                are supplied.
        """
        if len(self.bands) > MAX_EQ_BANDS:
            raise AudioConfigValueError(
                f"An EQ rack holds at most {MAX_EQ_BANDS} bands; got {len(self.bands)}",
                context={"field": "eq_bands", "value": len(self.bands)},
            )

    @property
    def active(self) -> bool:
        """Whether this rack changes the signal at all."""
        return bool(self.bands) and not self.bypass


def parse_band(text: str) -> EqBand:
    """Parse a ``kind,freq,gain,q`` band string.

    The Q field is optional, so ``"peaking,1000,3"`` is a valid band. This is
    the one parser the CLI flag and a hand-typed GUI row share.

    Args:
        text: A band string as :meth:`EqBand.describe` renders it.

    Returns:
        The parsed band.

    Raises:
        AudioConfigValueError: When the string does not carry two to four
            comma-separated fields or a field is not a number.
    """
    parts = [part.strip() for part in text.split(",")]
    if not 2 <= len(parts) <= 4:
        raise AudioConfigValueError(
            f"An EQ band is 'kind,freq[,gain[,q]]'; got {text!r}",
            context={"field": "eq_band", "value": text},
        )
    numbers: list[float] = []
    for index, part in enumerate(parts[1:], start=1):
        try:
            numbers.append(float(part))
        except ValueError as exc:
            raise AudioConfigValueError(
                f"EQ band field {index} of {text!r} is not a number: {part!r}",
                context={"field": "eq_band", "value": text},
            ) from exc
    gain = numbers[1] if len(numbers) > 1 else 0.0
    q = numbers[2] if len(numbers) > 2 else EQ_DEFAULT_Q
    kind = cast(BandKind, parts[0])
    return EqBand(kind=kind, freq_hz=numbers[0], gain_db=gain, q=q)


def build_eq_plugins(settings: EqSettings) -> list[Any]:
    """Return the pedalboard filters for *settings*, in rack order.

    Args:
        settings: The rack to build. A bypassed or empty rack builds nothing.

    Returns:
        A list of pedalboard filter objects, empty when the rack is inactive.
    """
    if not settings.active:
        return []

    from pedalboard import (
        HighpassFilter,
        HighShelfFilter,
        LowpassFilter,
        LowShelfFilter,
        PeakFilter,
    )

    plugins: list[Any] = []
    for band in settings.bands:
        if band.kind == "lowshelf":
            plugins.append(
                LowShelfFilter(
                    cutoff_frequency_hz=band.freq_hz, gain_db=band.gain_db, q=band.q
                )
            )
        elif band.kind == "highshelf":
            plugins.append(
                HighShelfFilter(
                    cutoff_frequency_hz=band.freq_hz, gain_db=band.gain_db, q=band.q
                )
            )
        elif band.kind == "peaking":
            plugins.append(
                PeakFilter(
                    cutoff_frequency_hz=band.freq_hz, gain_db=band.gain_db, q=band.q
                )
            )
        elif band.kind == "highpass":
            plugins.append(HighpassFilter(cutoff_frequency_hz=band.freq_hz))
        else:  # lowpass; EqBand has already validated the kind
            plugins.append(LowpassFilter(cutoff_frequency_hz=band.freq_hz))
    return plugins


def _check_nyquist(settings: EqSettings, sample_rate: int) -> None:
    """Refuse a band at or above the render's Nyquist frequency.

    A band the renderer cannot place is an error, not a band to clamp: silently
    moving it would apply a filter the user did not ask for.

    Args:
        settings: The rack about to be rendered.
        sample_rate: The rate the render will use, in Hz.

    Raises:
        AudioConfigValueError: When a band's frequency is at or above Nyquist.
    """
    nyquist = sample_rate / 2.0
    for band in settings.bands:
        if band.freq_hz >= nyquist:
            raise AudioConfigValueError(
                f"EQ band at {band.freq_hz:g} Hz is at or above this signal's "
                f"Nyquist frequency ({nyquist:g} Hz); decode at a higher rate "
                f"or lower the band",
                context={
                    "field": "eq_freq_hz",
                    "value": band.freq_hz,
                    "sample_rate": sample_rate,
                },
            )


def apply_eq(
    audio: npt.NDArray[np.floating[Any]],
    settings: EqSettings,
    sample_rate: int,
) -> npt.NDArray[np.floating[Any]]:
    """Apply *settings* to an ``(channels, samples)`` array.

    A bypassed or empty rack returns *audio* itself, not a copy, so the caller
    cannot observe a difference: that is the bit-transparency the EQ stage is
    held to (``np.array_equal`` and, through the write path, identical samples
    on disk).

    Args:
        audio: ``(channels, samples)`` float audio.
        settings: The rack to apply.
        sample_rate: The array's sample rate in Hz.

    Returns:
        The processed array, or *audio* unchanged when the rack is inactive.

    Raises:
        AudioConfigValueError: When a band is at or above Nyquist.
    """
    if not settings.active:
        return audio
    _check_nyquist(settings, sample_rate)

    from pedalboard import Pedalboard

    processed: npt.NDArray[np.floating[Any]] = Pedalboard(build_eq_plugins(settings))(
        audio, sample_rate
    )
    return processed


def response_curve(
    settings: EqSettings,
    freqs: npt.NDArray[np.floating[Any]],
    *,
    sample_rate: int = 44_100,
    fft_size: int = CURVE_FFT_SIZE,
) -> npt.NDArray[np.floating[Any]]:
    """Return the rack's measured magnitude response, in dB, at *freqs*.

    The curve is the FFT of the very filters :func:`apply_eq` renders, so a
    widget that draws it cannot show a shape the audio does not have.

    Args:
        settings: The rack to measure. An inactive rack is flat (all zeros).
        freqs: Frequencies in Hz at which to sample the response.
        sample_rate: The rate the response is measured at, in Hz.
        fft_size: Impulse-response length in samples.

    Returns:
        dB magnitude per requested frequency, same shape as *freqs*.

    Raises:
        AudioConfigValueError: When a band is at or above Nyquist.
    """
    points: npt.NDArray[np.floating[Any]] = np.asarray(freqs, dtype=np.float64)
    if not settings.active:
        flat: npt.NDArray[np.floating[Any]] = np.zeros_like(points)
        return flat
    _check_nyquist(settings, sample_rate)

    from pedalboard import Pedalboard

    impulse = np.zeros((1, fft_size), dtype=np.float32)
    impulse[0, 0] = 1.0
    rendered = np.asarray(
        Pedalboard(build_eq_plugins(settings))(impulse, sample_rate), dtype=np.float64
    )
    spectrum = np.abs(np.fft.rfft(rendered[0], n=fft_size))
    bin_hz = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    magnitude = np.interp(points, bin_hz, spectrum)
    curve: npt.NDArray[np.floating[Any]] = 20.0 * np.log10(np.maximum(magnitude, 1e-9))
    return curve
