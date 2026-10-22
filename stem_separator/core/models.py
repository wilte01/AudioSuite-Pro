"""
core/models.py
Data classes for the Stem Separator.

StemSeparationParams is the single source of truth for a run's settings: the
GUI, the CLI and the Master Driver all build one, and the processor reads only
this object.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Demucs' four-way split, in the order the model returns it.
STEM_NAMES: tuple[str, ...] = ("vocals", "drums", "bass", "other")

#: The default Demucs model.  ``htdemucs_ft`` is the fine-tuned variant: better
#: stems, roughly four times slower because it runs one model per stem.
DEFAULT_MODEL: str = "htdemucs"
MODEL_CHOICES: tuple[str, ...] = ("htdemucs", "htdemucs_ft")

#: Demucs operates at 44.1 kHz stereo; inputs are resampled to it.
MODEL_SAMPLE_RATE: int = 44100

#: Stems are written as 16-bit PCM WAV; the mix uses the same container.
STEM_SUFFIX: str = ".wav"

#: Filename of the optional recombined mix inside a track's output folder.
MIX_FILENAME: str = "mix.wav"


def normalise_stems(stems: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Return the stems to export, validated and in canonical order.

    Args:
        stems: Requested stem names; ``None`` or an empty sequence selects all
            four, which is what a run with no explicit selection means.

    Returns:
        The requested stems in :data:`STEM_NAMES` order, duplicates removed.

    Raises:
        ValueError: A requested name is not one of :data:`STEM_NAMES`, or the
            selection is empty after de-duplication.
    """
    if not stems:
        return STEM_NAMES
    unknown = sorted({stem for stem in stems if stem not in STEM_NAMES})
    if unknown:
        raise ValueError(f"unknown stem(s) {unknown}; choose from {list(STEM_NAMES)}")
    selected = tuple(stem for stem in STEM_NAMES if stem in set(stems))
    if not selected:
        raise ValueError("select at least one stem to export")
    return selected


@dataclass
class StemSeparationParams:
    """Everything a stem-separation run needs.

    Attributes:
        output_dir: Directory the per-track stem folders are written into.
            The source directory is never written to.
        stems: Stems to export; empty means all four.
        model: Demucs model name, one of :data:`MODEL_CHOICES`.
        write_mix: Also write ``mix.wav`` — the sum of the exported stems.
        device: ``"auto"``, ``"cpu"`` or ``"cuda"``; see
            :func:`audio_suite_shared.gpu_utils.resolve_device`.
        dry_run: Report what would be written without loading the model or
            creating any file.
    """

    output_dir: str = ""
    stems: tuple[str, ...] = field(default_factory=lambda: STEM_NAMES)
    model: str = DEFAULT_MODEL
    write_mix: bool = False
    device: str = "auto"
    dry_run: bool = False

    def resolved_stems(self) -> tuple[str, ...]:
        """Return the validated stem selection for this run."""
        return normalise_stems(self.stems)

    def validate(self) -> list[str]:
        """Return the problems that make this run impossible, as messages."""
        problems: list[str] = []
        if not self.output_dir.strip():
            problems.append("Choose an output directory for the separated stems.")
        if self.model not in MODEL_CHOICES:
            problems.append(
                f"Unknown model {self.model!r}; choose from {list(MODEL_CHOICES)}."
            )
        try:
            self.resolved_stems()
        except ValueError as exc:
            problems.append(str(exc))
        return problems


@dataclass(frozen=True)
class SeparatedTrack:
    """The floats Demucs produced for one source file.

    Attributes:
        sample_rate: Rate of every array in ``stems`` (Demucs' 44.1 kHz).
        stems: Stem name to a ``(channels, samples)`` float array in -1..1.
    """

    sample_rate: int
    stems: dict[str, Any]

    def duration_seconds(self) -> float:
        """Return the length of the longest stem, in seconds."""
        if not self.stems:
            return 0.0
        longest = max(int(array.shape[-1]) for array in self.stems.values())
        return longest / float(self.sample_rate)
