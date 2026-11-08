"""channel_ops.py — the suite's one implementation of channel maths.

Every channel operation the suite offers lives here, on the shared
channel-major float layout ``audio_conversion.segment_to_numpy`` produces:
``(channels, frames)``, float, normalised to [-1, 1].  A tool converts once,
calls :func:`apply_operation` and packs the result back with
``numpy_to_segment``; nothing transposes or rescales on its own.

The two mono rules are both offered, and they differ by a fixed 3.01 dB:

* :data:`MONO_MEAN` is ``0.5 * (L + R)``: the channel sum attenuated 6 dB.
* :data:`MONO_MINUS3DB` is ``(L + R) / sqrt(2)``: the same sum attenuated
  3 dB, so it is 3.01 dB louder than the mean for both a correlated pair and
  an uncorrelated one.  The tests measure that gap on both, so the two rules
  cannot be confused.  The name records the attenuation applied to the sum,
  not a promise about a centre-panned signal's level: a correlated pair sums
  to ``2L``, which the mean returns as ``L`` and this rule as ``1.41 L``.

``ms_encode`` writes M in the left channel and S in the right, which is what
makes ``ms_decode(ms_encode(x))`` a round trip; the pair is a storage
convention, not a claim that the file is no longer stereo.

A degenerate request is refused rather than guessed: an operation that needs
stereo refuses a mono file, mid/side and width refuse it too, and more than two
channels is refused outright instead of silently picking a pair.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from .audio_conversion import clip_to_range
from .exceptions import AudioConfigValueError

#: One 2-D float array, ``(channels, frames)``.
ChannelArray = npt.NDArray[np.float64]

#: Operations that are meaningful on either a mono or a stereo source.
MONO_MEAN = "mono_mean"
MONO_MINUS3DB = "mono_minus3db"
DUAL_MONO = "dual_mono"
INVERT_PHASE = "invert_phase"
MS_ENCODE = "ms_encode"
MS_DECODE = "ms_decode"
STEREO_WIDTH = "width"

#: The channels ``dual_mono`` may copy, and the sides ``invert_phase`` may flip.
CHANNEL_SIDES: tuple[str, ...] = ("left", "right")
INVERT_TARGETS: tuple[str, ...] = ("left", "right", "both")

#: Widest side gain offered.  100 % is unity, 0 % is mono, 200 % doubles the
#: side signal; beyond 400 % a stereo image is a special effect, not a tool.
MIN_WIDTH_PERCENT = 0.0
MAX_WIDTH_PERCENT = 400.0

#: The default side gain: unity, which changes nothing.
DEFAULT_WIDTH_PERCENT = 100.0

#: The default operation, and the one the command's help names first.
DEFAULT_OPERATION = MONO_MEAN


@dataclass(frozen=True)
class OperationSpec:
    """What one channel operation is and what it needs.

    Attributes:
        id: The operation's stored name, used by the CLI, the settings file and
            the GUI's combobox value.
        label: What the user sees, phrased as the outcome.
        needs_stereo: True when the operation cannot answer for a mono file.
        parameter: The extra setting the operation reads: ``"width"``,
            ``"channel"``, ``"invert"``, or ``""``.
    """

    id: str
    label: str
    needs_stereo: bool
    parameter: str = ""


#: Every operation, in the order the help and the window list them.
OPERATIONS: dict[str, OperationSpec] = {
    MONO_MEAN: OperationSpec(
        id=MONO_MEAN,
        label="Mono, arithmetic mean (0.5 x (L + R))",
        needs_stereo=False,
    ),
    MONO_MINUS3DB: OperationSpec(
        id=MONO_MINUS3DB,
        label="Mono, sum attenuated 3 dB ((L + R) / sqrt(2))",
        needs_stereo=False,
    ),
    DUAL_MONO: OperationSpec(
        id=DUAL_MONO,
        label="Dual mono (one channel copied to both)",
        needs_stereo=False,
        parameter="channel",
    ),
    INVERT_PHASE: OperationSpec(
        id=INVERT_PHASE,
        label="Invert phase (negate a channel or both)",
        needs_stereo=False,
        parameter="invert",
    ),
    MS_ENCODE: OperationSpec(
        id=MS_ENCODE,
        label="Mid/side encode (left = M, right = S)",
        needs_stereo=True,
    ),
    MS_DECODE: OperationSpec(
        id=MS_DECODE,
        label="Mid/side decode (L = M + S, R = M - S)",
        needs_stereo=True,
    ),
    STEREO_WIDTH: OperationSpec(
        id=STEREO_WIDTH,
        label="Stereo width (scale the side signal, then decode)",
        needs_stereo=True,
        parameter="width",
    ),
}

#: Operation ids in display order, for a CLI choice and a combobox's values.
OPERATION_IDS: tuple[str, ...] = tuple(OPERATIONS)


@dataclass(frozen=True)
class ChannelResult:
    """The audio an operation produced, and the rule that produced it.

    Attributes:
        audio: The processed ``(channels, frames)`` float64 array.
        rule: The sentence a run report carries, e.g. ``"mono sum: 0.5 x
            (L + R)"``.  It states the rule that ran, never the setting that
            asked for it.
        clipped: True when the result exceeded full scale and was clamped.
    """

    audio: ChannelArray
    rule: str
    clipped: bool = False


def _as_float64(audio: npt.NDArray[np.floating[Any]]) -> ChannelArray:
    """Return *audio* as a validated ``(channels, frames)`` float64 array.

    Args:
        audio: A 2-D float array in ``[-1, 1]``.

    Returns:
        The same samples, upcast to float64 (a copy when the input is not
        already float64).

    Raises:
        AudioConfigValueError: The array is not 2-D, holds no frames, or has
            more than two channels.
    """
    if audio.ndim != 2:
        raise AudioConfigValueError(
            "Channel operations expect a (channels, frames) array, got "
            f"{audio.ndim} dimension(s).",
            context={"dimensions": audio.ndim},
        )
    channels, frames = int(audio.shape[0]), int(audio.shape[1])
    if channels not in (1, 2):
        raise AudioConfigValueError(
            "Channel operations work on mono or stereo files; this one has "
            f"{channels} channels, and picking a pair would discard the rest.",
            context={"channels": channels},
        )
    if frames == 0:
        raise AudioConfigValueError(
            "Channel operations need at least one frame of audio; the file "
            "decoded empty.",
            context={"frames": 0},
        )
    converted: ChannelArray = np.asarray(audio, dtype=np.float64)
    return converted


def validate_operation(
    operation: str,
    *,
    width_percent: float = DEFAULT_WIDTH_PERCENT,
    source_channel: str = "left",
    invert_target: str = "both",
) -> None:
    """Refuse an operation request that names no meaningful rule.

    Args:
        operation: An id from :data:`OPERATIONS`.
        width_percent: Side gain for :data:`STEREO_WIDTH`.
        source_channel: Channel :data:`DUAL_MONO` copies.
        invert_target: Side :data:`INVERT_PHASE` negates.

    Raises:
        AudioConfigValueError: The operation is unknown, or one of its
            parameters is outside the documented set.
    """
    spec = OPERATIONS.get(operation)
    if spec is None:
        known = ", ".join(OPERATION_IDS)
        raise AudioConfigValueError(
            f"Unknown channel operation {operation!r}; expected one of {known}.",
            context={"operation": operation},
        )
    if spec.parameter == "width" and not (
        MIN_WIDTH_PERCENT <= width_percent <= MAX_WIDTH_PERCENT
    ):
        raise AudioConfigValueError(
            "Stereo width must be between "
            f"{MIN_WIDTH_PERCENT:g} and {MAX_WIDTH_PERCENT:g} percent, got "
            f"{width_percent:g}.",
            context={"width_percent": width_percent},
        )
    if spec.parameter == "channel" and source_channel not in CHANNEL_SIDES:
        raise AudioConfigValueError(
            f"Dual mono copies the left or the right channel, got {source_channel!r}.",
            context={"source_channel": source_channel},
        )
    if spec.parameter == "invert" and invert_target not in INVERT_TARGETS:
        raise AudioConfigValueError(
            f"Invert phase targets left, right or both, got {invert_target!r}.",
            context={"invert_target": invert_target},
        )


def _mean(samples: ChannelArray) -> ChannelArray:
    """Return the arithmetic mono mean as one channel."""
    mono: ChannelArray = np.asarray(
        0.5 * (samples[0] + samples[1]), dtype=np.float64
    ).reshape(1, -1)
    return mono


def _centre_preserving(samples: ChannelArray) -> ChannelArray:
    """Return ``(L + R) / sqrt(2)`` as one channel."""
    mono: ChannelArray = np.asarray(
        (samples[0] + samples[1]) / math.sqrt(2.0), dtype=np.float64
    ).reshape(1, -1)
    return mono


def _ms_components(samples: ChannelArray) -> tuple[ChannelArray, ChannelArray]:
    """Return the mid and side signals of a stereo pair."""
    mid: ChannelArray = np.asarray(0.5 * (samples[0] + samples[1]), dtype=np.float64)
    side: ChannelArray = np.asarray(0.5 * (samples[0] - samples[1]), dtype=np.float64)
    return mid, side


def _decoded(mid: ChannelArray, side: ChannelArray) -> ChannelArray:
    """Return the stereo pair a mid/side pair decodes to."""
    left: ChannelArray = np.asarray(mid + side, dtype=np.float64)
    right: ChannelArray = np.asarray(mid - side, dtype=np.float64)
    return np.stack([left, right])


def _with_clamp(audio: ChannelArray, rule: str) -> ChannelResult:
    """Clamp *audio* to full scale and say whether it needed it.

    Args:
        audio: The computed array.
        rule: The rule sentence to carry.

    Returns:
        The result, with ``clipped`` set when any sample left ``[-1, 1]``.
    """
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1.0:
        return ChannelResult(audio=audio, rule=rule)
    clipped: ChannelArray = np.asarray(clip_to_range(audio), dtype=np.float64)
    return ChannelResult(
        audio=clipped, rule=f"{rule} - clamped to full scale", clipped=True
    )


def apply_operation(
    audio: npt.NDArray[np.floating[Any]],
    operation: str,
    *,
    width_percent: float = DEFAULT_WIDTH_PERCENT,
    source_channel: str = "left",
    invert_target: str = "both",
) -> ChannelResult:
    """Apply one channel operation to a ``(channels, frames)`` array.

    Args:
        audio: The decoded samples, channel-major and normalised.
        operation: An id from :data:`OPERATIONS`.
        width_percent: Side gain for :data:`STEREO_WIDTH`; 100 is unity.
        source_channel: Channel :data:`DUAL_MONO` copies to both sides.
        invert_target: Side :data:`INVERT_PHASE` negates.

    Returns:
        The processed array and the rule sentence that produced it.

    Raises:
        AudioConfigValueError: The operation, its parameters, or the source's
            channel count cannot produce a meaningful result.
    """
    validate_operation(
        operation,
        width_percent=width_percent,
        source_channel=source_channel,
        invert_target=invert_target,
    )
    samples = _as_float64(audio)
    spec = OPERATIONS[operation]
    if spec.needs_stereo and samples.shape[0] < 2:
        raise AudioConfigValueError(
            f"{spec.label} needs a stereo file; this one is mono, and inventing "
            "a second channel would write audio the source never contained.",
            context={"operation": operation, "channels": int(samples.shape[0])},
        )

    if operation == MONO_MEAN:
        if samples.shape[0] == 1:
            return ChannelResult(audio=samples, rule="already mono - unchanged")
        return _with_clamp(_mean(samples), "mono sum: 0.5 x (L + R)")

    if operation == MONO_MINUS3DB:
        if samples.shape[0] == 1:
            return ChannelResult(audio=samples, rule="already mono - unchanged")
        return _with_clamp(_centre_preserving(samples), "mono sum: (L + R) / sqrt(2)")

    if operation == DUAL_MONO:
        source = 0 if source_channel == "left" else 1
        if samples.shape[0] == 1:
            channel = samples[0]
            rule = "dual mono: the mono channel copied to both sides"
        else:
            channel = samples[source]
            rule = f"dual mono: {source_channel} channel copied to both sides"
        return _with_clamp(np.stack([channel, channel]), rule)

    if operation == INVERT_PHASE:
        inverted = np.array(samples, dtype=np.float64, copy=True)
        targets = INVERT_TARGETS[:2] if invert_target == "both" else (invert_target,)
        if len(targets) == 2 and inverted.shape[0] < 2:
            raise AudioConfigValueError(
                "Inverting both sides needs a stereo file; this one is mono. "
                "Choose the mono file's own channel instead.",
                context={"operation": operation, "channels": 1},
            )
        for target in targets:
            index = 0 if target == "left" else 1
            inverted[index] = -inverted[index]
        sides = "both sides" if invert_target == "both" else f"{invert_target} channel"
        return ChannelResult(audio=inverted, rule=f"phase inverted: {sides}")

    mid, side = _ms_components(samples)

    if operation == MS_ENCODE:
        return ChannelResult(
            audio=np.stack([mid, side]),
            rule="mid/side encoded: left = M, right = S",
        )

    if operation == MS_DECODE:
        return _with_clamp(
            _decoded(samples[0], samples[1]), "mid/side decoded: L = M + S, R = M - S"
        )

    # STEREO_WIDTH, the only operation left after validation.
    if width_percent == DEFAULT_WIDTH_PERCENT:
        return ChannelResult(audio=samples, rule="stereo width 100 % - unchanged")
    scaled: ChannelArray = np.asarray(side * (width_percent / 100.0), dtype=np.float64)
    return _with_clamp(
        _decoded(mid, scaled), f"stereo width {width_percent:g} %: side scaled, decoded"
    )


def rule_for(
    operation: str,
    *,
    width_percent: float = DEFAULT_WIDTH_PERCENT,
    source_channel: str = "left",
    invert_target: str = "both",
) -> str:
    """Return the rule sentence a request would apply, without audio.

    A dry run has no decoded samples to measure, but it still has to say what
    it would do; this asks the same validation and the same spec table the
    live run uses, so the two can never describe the run differently.

    Args:
        operation: An id from :data:`OPERATIONS`.
        width_percent: Side gain for :data:`STEREO_WIDTH`.
        source_channel: Channel :data:`DUAL_MONO` copies.
        invert_target: Side :data:`INVERT_PHASE` negates.

    Returns:
        The operation's label, with its parameter where it has one.

    Raises:
        AudioConfigValueError: The request names no meaningful rule.
    """
    validate_operation(
        operation,
        width_percent=width_percent,
        source_channel=source_channel,
        invert_target=invert_target,
    )
    label = OPERATIONS[operation].label
    if operation == STEREO_WIDTH:
        return f"{label}; width {width_percent:g} %"
    if operation == DUAL_MONO:
        return f"{label}; source: {source_channel}"
    if operation == INVERT_PHASE:
        return f"{label}; target: {invert_target}"
    return label
