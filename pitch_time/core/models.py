"""models.py — the pitch/time settings and the output name they produce.

The two modes are the two transforms the engine offers, and a setting that
describes no change is refused here: re-encoding a file at ``rate 1.0`` would
lose a generation of quality and produce the same audio.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from audio_suite_shared.dsp_time_pitch import (
    MAX_RATE,
    MAX_SEMITONES,
    MIN_RATE,
    MIN_SEMITONES,
)
from audio_suite_shared.exceptions import AudioConfigValueError

#: Play the file faster or slower, pitch unchanged.
MODE_TEMPO = "tempo"

#: Move the pitch, length unchanged.
MODE_PITCH = "pitch"

#: Every mode, in the order the window lists them.
MODES: tuple[str, ...] = (MODE_TEMPO, MODE_PITCH)

#: How each mode is labelled in the window and the run report.
MODE_LABELS: dict[str, str] = {MODE_TEMPO: "Tempo", MODE_PITCH: "Pitch"}


@dataclass(frozen=True)
class PitchTimeSettings:
    """What one run does to every file it finds.

    Attributes:
        mode: ``"tempo"`` (stretch) or ``"pitch"`` (shift).
        rate: Speed factor for tempo mode; the pitch mode ignores it.
        semitones: Shift for pitch mode; the tempo mode ignores it.
    """

    mode: str = MODE_TEMPO
    rate: float = 1.0
    semitones: float = 0.0

    def __post_init__(self) -> None:
        """Refuse a mode or a value the engine cannot honour.

        Raises:
            AudioConfigValueError: The mode is unknown, a value is not finite or
        Raises:
            AudioConfigValueError: The mode is unknown, or a value is not finite
                or lies outside the engine's range.  A value that asks for no
                change is accepted: the run skips each file with that reason
                rather than re-encoding it (see :attr:`is_neutral`).
        """
        if self.mode not in MODES:
            raise AudioConfigValueError(
                f"Unknown mode {self.mode!r}; expected one of {', '.join(MODES)}.",
                context={"mode": self.mode},
            )
        if not math.isfinite(self.rate) or not MIN_RATE <= self.rate <= MAX_RATE:
            raise AudioConfigValueError(
                f"The rate must be between {MIN_RATE:g} and {MAX_RATE:g}, "
                f"got {self.rate:g}.",
                context={"rate": self.rate},
            )
        if (
            not math.isfinite(self.semitones)
            or not MIN_SEMITONES <= self.semitones <= MAX_SEMITONES
        ):
            raise AudioConfigValueError(
                f"The semitones must be between {MIN_SEMITONES:g} and "
                f"{MAX_SEMITONES:g}, got {self.semitones:g}.",
                context={"semitones": self.semitones},
            )
        if self.mode == MODE_TEMPO and self.rate == 1.0:
            # A neutral setting is allowed rather than refused: the Master
            # Driver enables a tool and runs it, so a refusal here would make
            # the batch fail rather than report that there was nothing to do.
            # ``is_neutral`` is what the run reads to skip instead.
            return
        if self.mode == MODE_PITCH and self.semitones == 0.0:
            return

    @property
    def is_neutral(self) -> bool:
        """Return whether this setting asks for no change at all."""
        if self.mode == MODE_TEMPO:
            return self.rate == 1.0
        return self.semitones == 0.0

    @property
    def factor(self) -> float:
        """Return the speed factor this setting applies."""
        if self.mode == MODE_TEMPO:
            return float(self.rate)
        return float(2.0 ** (self.semitones / 12.0))

    @property
    def description(self) -> str:
        """Return the one-line setting a report and the window both quote."""
        if self.mode == MODE_TEMPO:
            return f"Tempo rate {self.rate:g}x"
        return f"Pitch {self.semitones:+g} semitones"


def output_name(name: str, settings: PitchTimeSettings) -> str:
    """Return the file name a run writes for *name*.

    The source is never replaced: the new name carries the mode and the value,
    so two runs of the same folder cannot overwrite each other's output.

    Args:
        name: The source file's name (or path; only its last component is read).
        settings: The run's settings.

    Returns:
        ``<stem>_<mode>_<value><ext>``, e.g. ``song_tempo_1.25.wav`` or
        ``song_pitch_-2st.flac``.
    """
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem, dot, extension = base.rpartition(".")
    if not dot:
        stem, extension = base, ""
    if settings.mode == MODE_TEMPO:
        marker = f"tempo_{settings.rate:g}"
    else:
        marker = f"pitch_{settings.semitones:+g}st"
    suffix = f".{extension}" if extension else ""
    return f"{stem}_{marker}{suffix}"
