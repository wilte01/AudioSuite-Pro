"""crossfade.py — the equal-power overlap between two segments.

An equal-power fade multiplies the outgoing tail by ``cos`` and the incoming
head by ``sin`` over the same quarter turn, so two correlated signals keep their
level instead of dipping by 3 dB the way two linear fades would.  The mix is
computed on the decoded integer frames and clipped back into the segment's own
sample width, so the result is a real audio outcome rather than a settings
read-back.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment


def _frames(segment: AudioSegment) -> npt.NDArray[np.float64]:
    """Return *segment*'s samples as a ``(frames, channels)`` float array."""
    channels = segment.channels
    samples: npt.NDArray[np.float64] = np.array(
        segment.get_array_of_samples(), dtype=np.float64
    )
    return samples.reshape(-1, channels)


def _segment(frames: npt.NDArray[np.float64], template: AudioSegment) -> AudioSegment:
    """Return a segment built from float *frames* using *template*'s format."""
    width = template.sample_width
    peak = float(2 ** (8 * width - 1) - 1)
    clipped: npt.NDArray[np.float64] = np.clip(np.rint(frames), -peak - 1, peak)
    packed: npt.NDArray[np.signedinteger[Any]] = clipped.astype(f"<i{width}")
    data = packed.tobytes()
    return AudioSegment(
        data=data,
        sample_width=width,
        frame_rate=template.frame_rate,
        channels=template.channels,
    )


def equal_power_mix(
    outgoing: AudioSegment, incoming: AudioSegment, overlap_ms: int
) -> AudioSegment:
    """Overlap the tail of *outgoing* with the head of *incoming*.

    Args:
        outgoing: The segment that ends the boundary.
        incoming: The segment that starts it.
        overlap_ms: Overlap length; must be positive and not longer than
            either segment.

    Returns:
        The combined audio: ``outgoing`` without its tail, the crossfaded
        overlap, then ``incoming`` without its head.

    Raises:
        ValueError: The overlap is not positive or is longer than a segment,
            or the two segments disagree about channels or sample rate.
    """
    if overlap_ms <= 0:
        raise ValueError(f"The overlap must be positive, got {overlap_ms} ms.")
    if len(outgoing) < overlap_ms or len(incoming) < overlap_ms:
        raise ValueError(
            f"A {overlap_ms} ms overlap does not fit the "
            f"{len(outgoing)}/{len(incoming)} ms segments."
        )
    if (
        outgoing.channels != incoming.channels
        or outgoing.frame_rate != incoming.frame_rate
    ):
        raise ValueError(
            "A crossfade needs both segments at the same channel count and "
            "sample rate; convert them first."
        )
    if outgoing.sample_width != incoming.sample_width:
        raise ValueError(
            "A crossfade needs both segments at the same sample width; "
            "convert them first."
        )

    head = outgoing[: len(outgoing) - overlap_ms]
    tail = outgoing[len(outgoing) - overlap_ms :]
    lead = incoming[:overlap_ms]
    rest = incoming[overlap_ms:]

    tail_frames = _frames(tail)
    lead_frames = _frames(lead)
    theta = np.linspace(0.0, np.pi / 2, len(tail_frames), dtype=np.float64).reshape(
        -1, 1
    )
    mixed = tail_frames * np.cos(theta) + lead_frames * np.sin(theta)
    return head + _segment(mixed, outgoing) + rest
