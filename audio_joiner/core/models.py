"""models.py — the joiner's settings and the arithmetic its plan states.

The plan's length is a pure function of the segments' lengths and the two
boundary settings, so it can be tested without decoding a file:
:func:`plan_duration_ms` is what both the window and the run report quote, and
:func:`validate_overlap` refuses a crossfade longer than the clip it fades.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioConfigValueError

#: Silence inserted between two segments, in milliseconds.
DEFAULT_GAP_MS = 0

#: Overlap of two segments' tails and heads, in milliseconds.
DEFAULT_CROSSFADE_MS = 0

#: Suffix the window appends to the first segment's stem for its output name.
DEFAULT_OUTPUT_SUFFIX = "_joined"


@dataclass(frozen=True)
class JoinSettings:
    """How a join treats the boundary between two segments.

    Attributes:
        gap_ms: Silence inserted at every boundary.  Zero means the segments
            meet end to end.
        crossfade_ms: Equal-power overlap at every boundary.  Zero means no
            overlap.  A gap and a crossfade describe the same boundary two
            ways, so a run may set one or the other, never both.
        copy_when_compatible: Use FFmpeg's stream copy when every input shares
            the first one's codec and parameters and no boundary processing is
            asked for.  Copying avoids a generation of lossy re-encoding.
    """

    gap_ms: int = DEFAULT_GAP_MS
    crossfade_ms: int = DEFAULT_CROSSFADE_MS
    copy_when_compatible: bool = True

    def __post_init__(self) -> None:
        """Reject a setting no boundary could honour.

        Raises:
            AudioConfigValueError: A length is negative, or both a gap and a
                crossfade are asked for.
        """
        if self.gap_ms < 0:
            raise AudioConfigValueError(
                f"The gap must not be negative, got {self.gap_ms} ms.",
                context={"gap_ms": self.gap_ms},
            )
        if self.crossfade_ms < 0:
            raise AudioConfigValueError(
                f"The crossfade must not be negative, got {self.crossfade_ms} ms.",
                context={"crossfade_ms": self.crossfade_ms},
            )
        if self.gap_ms and self.crossfade_ms:
            raise AudioConfigValueError(
                "Set a crossfade or a gap, not both: they describe the same "
                "boundary two ways.",
                context={"gap_ms": self.gap_ms, "crossfade_ms": self.crossfade_ms},
            )

    @property
    def processes_boundaries(self) -> bool:
        """Return whether the run changes the audio at a boundary."""
        return bool(self.gap_ms or self.crossfade_ms)


def validate_overlap(durations_ms: Sequence[int], crossfade_ms: int) -> None:
    """Refuse a crossfade longer than the shortest segment it overlaps.

    Args:
        durations_ms: Every segment's measured length.
        crossfade_ms: The requested overlap.

    Raises:
        AudioConfigValueError: The overlap is not shorter than a segment, so
            the fade would consume more audio than the segment contains.
    """
    if not crossfade_ms or not durations_ms:
        return
    shortest = min(durations_ms)
    if crossfade_ms >= shortest:
        raise AudioConfigValueError(
            f"A {crossfade_ms} ms crossfade is not shorter than the shortest "
            f"segment ({shortest} ms), so it would consume the whole of it.",
            context={"crossfade_ms": crossfade_ms, "shortest_ms": shortest},
        )


def plan_duration_ms(durations_ms: Sequence[int], settings: JoinSettings) -> int:
    """Return the length a join of these segments would produce.

    Args:
        durations_ms: Every segment's measured length, in join order.
        settings: The boundary settings.

    Returns:
        ``sum + gaps - overlaps``: each boundary adds a gap or removes the
        overlapped audio, never both.

    Raises:
        AudioConfigValueError: There are no segments, or the crossfade is not
            shorter than the shortest one.
    """
    if not durations_ms:
        raise AudioConfigValueError(
            "A join needs at least one segment, so there is no length to plan.",
            context={"segments": 0},
        )
    validate_overlap(durations_ms, settings.crossfade_ms)
    boundaries = len(durations_ms) - 1
    total = sum(durations_ms)
    if settings.crossfade_ms:
        return total - boundaries * settings.crossfade_ms
    return total + boundaries * settings.gap_ms


def output_name(first: str, extension: str, suffix: str = DEFAULT_OUTPUT_SUFFIX) -> str:
    """Return the default output file name for a join.

    Args:
        first: The first segment's file name (or path).
        extension: The output extension, with or without its leading dot.
        suffix: The marker appended to the first segment's stem.

    Returns:
        ``<stem><suffix><ext>``, so a folder's join lands beside its parts
        without replacing any of them.
    """
    stem = first.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    dot = stem.rfind(".")
    if dot > 0:
        stem = stem[:dot]
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{stem}{suffix}{ext}"
