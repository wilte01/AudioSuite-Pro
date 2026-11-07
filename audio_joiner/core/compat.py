"""compat.py — do these inputs share one stream, or must they be re-encoded?

A file's extension does not say whether two files can be stream-copied
together: two MP3s at different sample rates are both ``.mp3`` and the concat
demuxer produces a broken file from them.  Every input is therefore probed and
compared on the four parameters the demuxer requires, and a mismatch is a
report line the run publishes rather than a silent copy.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.audio_probe import StreamInfo, probe_stream
from audio_suite_shared.exceptions import AudioConfigValueError


@dataclass(frozen=True)
class CompatibilityReport:
    """What every input's stream says, and whether one copy can carry them.

    Attributes:
        streams: One probe per input, in join order.
        identical: True when every input matches the first on codec, sample
            rate, channel count and container.
        sample_rate: The first input's sample rate: the copy target, and the
            re-encode target when the inputs differ.
        channels: The first input's channel count, on the same terms.
        mismatch: The first input that differs from the first one, named with
            its parameters, or an empty string when they all match.
    """

    streams: tuple[StreamInfo, ...]
    identical: bool
    sample_rate: int
    channels: int
    mismatch: str = ""


def probe_inputs(paths: Sequence[Path]) -> CompatibilityReport:
    """Probe every input and compare it with the first.

    Args:
        paths: The files to join, in order.

    Returns:
        The report; ``identical`` says whether a stream copy is possible.

    Raises:
        AudioConfigValueError: No inputs were given.
        AudioFormatError: An input cannot be probed.
    """
    if not paths:
        raise AudioConfigValueError(
            "A join needs at least two files, so none were given.",
            context={"files": 0},
        )
    streams = tuple(probe_stream(str(path)) for path in paths)
    first = streams[0]
    signature = (first.codec, first.sample_rate, first.channels, first.container)
    mismatch = ""
    for path, stream in zip(paths[1:], streams[1:]):
        if (stream.codec, stream.sample_rate, stream.channels, stream.container) != (
            signature
        ):
            mismatch = (
                f"{path.name}: {stream.codec}, {stream.sample_rate} Hz, "
                f"{stream.channels} ch in {stream.container} against the first "
                f"file's {first.codec}, {first.sample_rate} Hz, "
                f"{first.channels} ch in {first.container}"
            )
            break
    return CompatibilityReport(
        streams=streams,
        identical=not mismatch,
        sample_rate=first.sample_rate,
        channels=first.channels,
        mismatch=mismatch,
    )
