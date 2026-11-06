"""models.py — the splitter's settings, gaps and planned tracks.

The three types here are pure data plus one planning function, so the split
plan can be tested without decoding audio: :func:`plan_tracks` turns detected
silent runs into the tracks a run would write.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioConfigValueError

#: Where inside a detected silent run the cut lands.
#:
#: ``midpoint`` splits the run evenly between the two tracks, ``start`` leaves
#: the run at the head of the following track and ``end`` leaves it at the tail
#: of the preceding one.  A leading run always cuts at its end and a trailing
#: run always cuts at its start, whichever rule is chosen: those runs belong to
#: no track, and halving them would put half a second of silence in front of
#: track one.
BOUNDARY_RULES: tuple[str, ...] = ("midpoint", "start", "end")

DEFAULT_BOUNDARY = "midpoint"

#: What a track is called when the source carries no usable title.
DEFAULT_NAMING = "{track:02d} - {title}"

#: Prefix a generated title carries when the source has no title tag.
DEFAULT_TITLE_PREFIX = "Track"


@dataclass(frozen=True)
class Gap:
    """One detected silent run inside a file.

    Attributes:
        start_ms: First millisecond of the run.
        end_ms: First millisecond after it.
    """

    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        """Length of the run in milliseconds."""
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class SplitSettings:
    """How a split run detects gaps and names what it writes.

    Attributes:
        min_silence_ms: Shortest silent run the detector reports as a gap.
        silence_db: Level at or below which FFmpeg treats audio as silence,
            relative to full scale (so ``-45`` is 45 dB down).
        min_track_ms: Shortest track a plan keeps; a shorter segment is merged
            into its neighbour rather than written as a fragment.
        boundary: One of :data:`BOUNDARY_RULES`.
        naming_pattern: Filename pattern; see :mod:`track_splitter.core.naming`.
        write_cue: Also write a ``.cue`` sheet describing the source image.
    """

    min_silence_ms: int = 700
    silence_db: float = -45.0
    min_track_ms: int = 5000
    boundary: str = DEFAULT_BOUNDARY
    naming_pattern: str = DEFAULT_NAMING
    write_cue: bool = False

    def __post_init__(self) -> None:
        """Reject a setting no run could honour.

        Raises:
            AudioConfigValueError: A length is not positive, the threshold is
                not below full scale, or the boundary rule is unknown.
        """
        if self.min_silence_ms <= 0:
            raise AudioConfigValueError(
                "The minimum silence length must be positive, got "
                f"{self.min_silence_ms} ms.",
                context={"min_silence_ms": self.min_silence_ms},
            )
        if self.min_track_ms <= 0:
            raise AudioConfigValueError(
                "The minimum track length must be positive, got "
                f"{self.min_track_ms} ms.",
                context={"min_track_ms": self.min_track_ms},
            )
        if self.silence_db >= 0:
            raise AudioConfigValueError(
                "The silence threshold must be below 0 dBFS, got "
                f"{self.silence_db} dB.",
                context={"silence_db": self.silence_db},
            )
        if self.boundary not in BOUNDARY_RULES:
            expected = ", ".join(BOUNDARY_RULES)
            raise AudioConfigValueError(
                f"Unknown track boundary {self.boundary!r}; use one of {expected}.",
                context={"boundary": self.boundary},
            )


@dataclass(frozen=True)
class Track:
    """One track a run would write, in source milliseconds.

    Attributes:
        number: 1-based track number.
        start_ms: First millisecond kept.
        end_ms: First millisecond after the kept audio.
        title: Rendered title for the track.
    """

    number: int
    start_ms: int
    end_ms: int
    title: str

    @property
    def duration_ms(self) -> int:
        """Length of the track in milliseconds."""
        return self.end_ms - self.start_ms


def _cut_for(gap: Gap, boundary: str) -> int:
    """Return where an interior *gap* cuts the file."""
    if boundary == "start":
        return gap.start_ms
    if boundary == "end":
        return gap.end_ms
    return (gap.start_ms + gap.end_ms) // 2


def _merge_short(
    segments: list[tuple[int, int]], min_track_ms: int
) -> list[tuple[int, int]]:
    """Merge segments shorter than *min_track_ms* into a neighbour.

    A merge extends the partition rather than dropping it, so the tracks still
    cover the file end to end and no sample is lost: a 200 ms fragment between
    two gaps joins the track before it (or, when it is the first segment, the
    track after it).
    """
    if len(segments) <= 1:
        return segments
    merged: list[tuple[int, int]] = []
    for index, (start, end) in enumerate(segments):
        short = end - start < min_track_ms
        if short and merged:
            merged[-1] = (merged[-1][0], end)
        elif short and index + 1 < len(segments):
            nxt_start, nxt_end = segments[index + 1]
            segments[index + 1] = (start, nxt_end)
        else:
            merged.append((start, end))
    return merged


def plan_tracks(
    gaps: list[Gap],
    total_ms: int,
    settings: SplitSettings,
    *,
    title_prefix: str = "",
) -> list[Track]:
    """Turn detected *gaps* into the tracks a run would write.

    Args:
        gaps: Silent runs, in file order.
        total_ms: The source's measured length.
        settings: The run's settings; ``boundary`` and ``min_track_ms`` decide
            where the cuts land and which fragments are merged.
        title_prefix: A title stem from the source's own tags.  Empty means
            "Track" and no tag was found.

    Returns:
        The planned tracks.  The cuts partition the audio between the source's
        leading and trailing silence, so the durations sum to the source length
        minus the silence at its ends.

    Raises:
        AudioConfigValueError: The source has no measurable length.
    """
    if total_ms <= 0:
        raise AudioConfigValueError(
            "The source has no measurable length, so there is nothing to split.",
            context={"total_ms": total_ms},
        )
    runs = [gap for gap in gaps if gap.duration_ms > 0]
    # Leading and trailing silence belongs to no track: writing it would make
    # track one a half-second of nothing.  It is discarded, not merged.
    origin = max((gap.end_ms for gap in runs if gap.start_ms <= 0), default=0)
    limit = min(
        (gap.start_ms for gap in runs if gap.end_ms >= total_ms), default=total_ms
    )
    if limit <= origin:
        raise AudioConfigValueError(
            "The file is silent throughout, so there is nothing to split.",
            context={"total_ms": total_ms},
        )
    interior = [gap for gap in runs if gap.start_ms > 0 and gap.end_ms < total_ms]
    cuts = {
        clamp
        for gap in interior
        for clamp in [min(max(_cut_for(gap, settings.boundary), origin), limit)]
        if origin < clamp < limit
    }
    edges = [origin, *sorted(cuts), limit]
    segments = list(zip(edges[:-1], edges[1:]))
    kept = _merge_short(segments, settings.min_track_ms)

    prefix = title_prefix.strip() or DEFAULT_TITLE_PREFIX
    return [
        Track(
            number=index,
            start_ms=start,
            end_ms=end,
            title=f"{prefix} {index:02d}",
        )
        for index, (start, end) in enumerate(kept, start=1)
    ]
