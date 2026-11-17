"""
core/models.py
Data classes for the Noise Reduction library.

``NoiseReductionParams`` holds every user-configurable setting for both halves of
the stage - hum removal and broadband noise reduction - and for the broadband
half it also says *which* engine runs: the spectral gate this package
implements, or the RNNoise model the neural engine runs.  Audio Refinery's
pipeline, its setup panel, its settings file and its CLIs all read this one
object, so "which denoiser" is a field on the run rather than a second window
to find.

Changed in 2.8.0: ``broadband_engine`` and ``neural_amount`` add the neural
engine to the stage.  The default stays ``"spectral"``, so every preset,
settings file and run written before it is unchanged, and a source wider than
the model's 16-bit output is refused rather than accepted at a lower depth -
REFINE's export preserves the source's bit depth, so there is no third state to
configure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from pydub import AudioSegment

# Changed in 2.8.0: the neural engine's constants and result moved here with the
# engine.  They stay the single declaration the engine, the stage and the CLIs
# read.
#: The neural engine's frame size: 10 ms at RNNoise's internal 48 kHz rate.
FRAME_SIZE: int = 480

#: The rate RNNoise works at internally (it resamples in and back out).
MODEL_SAMPLE_RATE: int = 48000

#: Default blend: the model's output, unmodified.  A lower value keeps part of
#: the source, which is what a music file needs from a speech model.
DEFAULT_AMOUNT: float = 1.0

#: A blend of 0% would hand the source back unchanged, so it is refused.
MIN_AMOUNT: float = 0.0

#: Attenuation below this is measurement noise, not a repair: the stage reports
#: the file as unchanged and writes nothing.
MIN_CHANGE_DB: float = 0.1

#: Floor used when an RMS of exactly zero would make the dB value -inf.
SILENCE_FLOOR_DBFS: float = -120.0

#: The default blend, under the name the noise stage reads it by.
NEURAL_DEFAULT_AMOUNT: float = DEFAULT_AMOUNT


class DenoiseResult(NamedTuple):
    """The outcome of one neural pass, in the stage's own shape.

    Attributes:
        audio: The processed segment, at the source's rate and channel count,
            with the same number of samples as the source.
        rms_before_db: Global RMS of the source, in dBFS.
        rms_after_db: Global RMS of ``audio``, in dBFS.
        was_modified: Whether the level moved by at least
            :data:`MIN_CHANGE_DB`.  A file the model left alone is reported
            clean and is never rewritten.
    """

    audio: AudioSegment
    rms_before_db: float
    rms_after_db: float
    was_modified: bool

    def attenuation_db(self) -> float:
        """Return how much the level dropped, in dB (never negative)."""
        return max(self.rms_before_db - self.rms_after_db, 0.0)


#: The engines the broadband half can run.
#:
#: ``spectral`` is this package's STFT gate: it needs a noise profile and keeps
#: every bin above the measured floor.  ``neural`` is RNNoise, the speech-trained
#: model :mod:`noise_reduction.core.rnnoise_engine` runs: no profile, a fresh
#: estimate every 10 ms frame, and heavy attenuation of tonal content.  Declared
#: once because the engine,
#: the setup panel, the settings loader and both CLIs validate against it.
BROADBAND_ENGINES: tuple[str, ...] = ("spectral", "neural")

#: The profile-gate engine, and the default.
SPECTRAL_ENGINE: str = "spectral"

#: The learned engine.
NEURAL_ENGINE: str = "neural"

#: The resolution the neural engine's output carries, whatever the source's.
NEURAL_OUTPUT_BITS: int = 16


@dataclass(frozen=True)
class HumLine:
    """One mains-hum partial and how far it stands above its local floor.

    ``prominence_db`` is the measured peak power density against the median of
    the surrounding band, so a quiet recording with real hum still scores high
    and a loud recording without hum scores near zero - the strength is
    relative, which is what makes one threshold work across a library.
    """

    order: int
    frequency_hz: float
    prominence_db: float


@dataclass(frozen=True)
class NoiseWindow:
    """The stretch the spectral gate measured its noise floor from.

    Chosen by the file rather than by a fixed default: the first 500 ms of a
    track is usually an intro with content in it, and a profile taken there
    either gates nothing or gates the music.  ``flatness`` is the mean spectral
    flatness of the window (1.0 is noise-like, near 0 is tonal), so a quiet
    stretch of a quiet chord is not mistaken for noise.
    """

    start_ms: int
    end_ms: int
    rms_dbfs: float
    flatness: float
    #: How much dB a gate built from this window's profile removes from the
    #: file's loudest stretch.  This is the candidate guard, not the decider: a
    #: window close in level to the content answers with decibels and is
    #: dropped, while quiet candidates all answer with about 0 dB - measured
    #: 0.00 on a music/rest/hiss file - so flatness separates a rest from hiss.
    trial_db: float

    def describe(self) -> str:
        """Return the report form.

        E.g. ``auto 12.4-12.8 s at -62 dBFS, trial 0.8 dB``.
        """
        return (
            f"auto {self.start_ms / 1000.0:.1f}-{self.end_ms / 1000.0:.1f} s "
            f"at {self.rms_dbfs:.0f} dBFS, trial {self.trial_db:.1f} dB"
        )


@dataclass(frozen=True)
class NoiseAnalysis:
    """What the noise detectors found in one file, before anything ran.

    The panel's Analyse action reports this and nothing else.  The numbers come
    from the batch's own ``detect_hum`` and ``detect_noise_profile``, so a
    preview cannot promise a profile the run would not choose, and no part of
    this measurement writes, exports or mutates the source.
    """

    hum: HumProfile | None
    window: NoiseWindow | None
    file_rms_dbfs: float
    duration_s: float

    @property
    def noise_floor_dbfs(self) -> float:
        """The floor the gate would use: the window's level, else the file's."""
        return self.window.rms_dbfs if self.window is not None else self.file_rms_dbfs

    def describe(self, file_name: str = "") -> str:
        """Return the read-only report the panel shows."""
        measured = f"Measured {file_name}" if file_name else "Measured this file"
        lines = [
            f"{measured} ({self.duration_s:.1f} s) - nothing was processed or written.",
        ]
        if self.hum is not None:
            lines.append(f"Hum: {self.hum.describe()}")
        else:
            lines.append("Hum: none detected in the first 30 s")
        if self.window is not None:
            lines.append(
                f"Noise floor: {self.noise_floor_dbfs:.0f} dBFS over "
                f"{self.window.describe()}"
            )
            lines.append(
                "Recommended profile region: "
                f"{self.window.start_ms}-{self.window.end_ms} ms"
            )
        else:
            lines.append(f"Noise floor: {self.file_rms_dbfs:.0f} dBFS (whole file)")
            lines.append(
                "Recommended profile region: too short to measure, so the "
                "configured region applies"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class HumProfile:
    """What the hum detector measured: the mains frequency and its live partials.

    Only the lines in ``lines`` are notched, which is the point of measuring:
    a 50 Hz recording no longer loses eight 60 Hz-spaced notches out of its
    bass, and a hum that carries only its fundamental no longer loses seven
    silent ones.
    """

    fundamental_hz: int
    lines: tuple[HumLine, ...]

    @property
    def orders(self) -> tuple[int, ...]:
        """The harmonic orders that measured above the floor, ascending."""
        return tuple(line.order for line in self.lines)

    @property
    def level_db(self) -> float:
        """The strongest measured partial's prominence in dB."""
        return max(line.prominence_db for line in self.lines)

    def describe(self) -> str:
        """Return the report form, e.g. ``50 Hz auto, 3 harmonics, 21 dB``."""
        count = len(self.lines)
        noun = "harmonic" if count == 1 else "harmonics"
        return (
            f"{self.fundamental_hz} Hz auto, {count} {noun}, "
            f"{self.level_db:.0f} dB above floor"
        )


@dataclass
class NoiseReductionParams:
    """Parameters for noise reduction processing."""

    # Hum removal
    reduce_hum: bool = False
    #: Detect the mains frequency and its live partials instead of notching a
    #: fixed cascade.  The default, because the region a file came from decides
    #: 50 or 60 Hz and a wrong guess both misses the hum and notches the music.
    hum_auto: bool = True
    #: The manual override, used when ``hum_auto`` is off.
    hum_frequency: int = 60  # 50 or 60 Hz
    hum_harmonics: int = 8  # highest harmonic the detector reports (1-20)
    hum_quality: float = 30.0  # Q factor for notch filters (1.0-100.0)

    # Broadband noise reduction
    reduce_broadband: bool = False
    #: Pick the quietest, flattest stretch of each file as the noise profile.
    #: The default, because a fixed first-500-ms window is an intro more often
    #: than it is noise.  The manual region below is the override.
    profile_auto: bool = True
    noise_start_ms: int = 0  # start of the manual noise profile region
    noise_end_ms: int = 500  # end of the manual noise profile region
    gate_threshold_db: float = 3.0  # gating threshold dB above noise floor
    #: Which broadband engine runs (:data:`BROADBAND_ENGINES`).  Read only when
    #: ``reduce_broadband`` is set; the three profile fields above belong to the
    #: spectral engine.
    broadband_engine: str = SPECTRAL_ENGINE
    #: How much of the neural engine's output to keep, 0-1.  The model's own
    #: result at 1.0; lower values blend the source back in, which is what music
    #: needs from a model trained on speech.
    neural_amount: float = NEURAL_DEFAULT_AMOUNT
    #: Whether a source wider than the model's 16-bit output may be narrowed to
    #: it.  Off by default: REFINE's export preserves the source's bit depth, so
    #: a run refuses a wider source rather than silently dropping resolution.
    #: Turning it on is an explicit choice, and the stage line and run report
    #: then state the 16-bit output the written file carries.
    allow_16bit_output: bool = False

    # Common
    dry_run: bool = False

    def neural_selected(self) -> bool:
        """Return whether this parameter set runs the neural engine.

        The one place the rule lives: the engine, its dependency and bit-depth
        guards, the setup panel, the Driver's argv and the writer all ask this
        instead of re-deriving the pair and drifting apart.
        """
        return bool(self.reduce_broadband and self.broadband_engine == NEURAL_ENGINE)


#: Below this the stage changed bytes without removing anything audible.  That
#: is a no-op rather than a clean file (which never reaches the gate's write),
#: so the stage line warns instead of reporting a result it did not achieve.
MIN_MEANINGFUL_ATTENUATION_DB: float = 0.5


class NoiseReductionResult(NamedTuple):
    """Result of noise reduction processing."""

    audio: AudioSegment
    energy_before_db: float
    energy_after_db: float
    was_modified: bool
    #: What the hum detector measured, when it ran; ``None`` for a manual
    #: cascade or a run with hum removal off.  The stage reports it.
    hum_profile: HumProfile | None = None
    #: The window the spectral gate measured its floor from, when it chose one.
    noise_window: NoiseWindow | None = None
    #: What the broadband gate removed on its own, in dB.  The stage's
    #: ``energy_before_db``/``energy_after_db`` span hum removal as well, so the
    #: gate's share is measured where only the gate ran.
    gate_attenuation_db: float | None = None
    #: Share (0-1) of the gate's time-frequency bins it suppressed.  A gate that
    #: removes a lot of decibels from a handful of bins and one that thins every
    #: bin by a little read the same in dB; this tells them apart.
    gated_bin_share: float | None = None
